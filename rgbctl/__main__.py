"""Command line entry point.

  rgbctl                      open the window
  rgbctl --tray               start hidden in the tray (used at login)
  rgbctl --headless           run without any window (e.g. as a service)
  rgbctl effects              list effects
  rgbctl set <effect> [--color1 HEX] [--color2 HEX] [--speed N] [--brightness N] [--rainbow/--no-rainbow]
  rgbctl off
  rgbctl profile <name>       apply a saved profile
  rgbctl profiles             list saved profiles
  rgbctl status               show the current settings
  rgbctl setup                guided setup (devices, fan headers, LEDs per fan)
"""
from __future__ import annotations

import argparse
import fcntl
import os
import re
import signal
import subprocess
import sys
import time

from .config import (CONFIG_DIR, LOCK_FILE, PROJECT_DIR, STATE_FILE, list_profiles, load_profile,
                     load_state, save_state)
from .effects import EFFECTS


def _instance_running() -> bool:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOCK_FILE, "a") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True
        fcntl.flock(f, fcntl.LOCK_UN)
    return False


_lock_handle = None


def _take_lock(mode: str) -> bool:
    """Only one rgbctl drives the lights. The lock file records 'pid mode'."""
    global _lock_handle
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _lock_handle = open(LOCK_FILE, "a+")
    try:
        fcntl.flock(_lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    _lock_handle.seek(0)
    _lock_handle.truncate()
    _lock_handle.write(f"{os.getpid()} {mode}\n")
    _lock_handle.flush()
    return True


def _lock_owner() -> tuple[int, str] | None:
    try:
        pid, mode = LOCK_FILE.read_text().split()
        return int(pid), mode
    except (OSError, ValueError):
        return None


def _start_gui(tray: bool) -> int:
    if not _take_lock("gui"):
        owner = _lock_owner()
        if owner and owner[1] == "gui":
            os.kill(owner[0], signal.SIGUSR1)  # ask the open app to show its window
            print("RGB Control is already running; showing its window.")
            return 0
        if owner:  # a headless instance: hand over to the window
            os.kill(owner[0], signal.SIGTERM)
        for _ in range(50):
            time.sleep(0.1)
            if _take_lock("gui"):
                break
        else:
            print("Another rgbctl is running and did not stop.")
            return 1
    from .gui import run
    return run(start_hidden=tray)


def _ensure_running() -> None:
    """After a CLI change, make sure something is driving the lights."""
    if _instance_running():
        print("Applied (running instance picked it up).")
        return
    subprocess.Popen([str(PROJECT_DIR / "bin" / "rgbctl"), "--headless"], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    print("Applied (started rgbctl in the background).")


def _hex(s: str) -> str:
    s = s.strip().lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", s):
        raise argparse.ArgumentTypeError("color must be 6 hex digits, e.g. ff0000")
    return "#" + s.lower()


def run_headless() -> int:
    if not _take_lock("headless"):
        print("rgbctl is already running.")
        return 1
    from .engine import Engine
    state = load_state()
    eng = Engine(state)
    eng.start()
    stop = []
    signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
    signal.signal(signal.SIGINT, lambda *_: stop.append(1))
    mtime = STATE_FILE.stat().st_mtime if STATE_FILE.exists() else 0
    while not stop:
        time.sleep(0.5)
        m = STATE_FILE.stat().st_mtime if STATE_FILE.exists() else 0
        if m != mtime:
            mtime = m
            eng.update_state(load_state())
    eng.stop()
    eng.join(2)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="rgbctl", description="Control and sync RGB lighting.")
    ap.add_argument("--tray", action="store_true", help="start hidden in the system tray")
    ap.add_argument("--headless", action="store_true", help="run without a window")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("effects", help="list effects")
    s = sub.add_parser("set", help="set an effect")
    s.add_argument("effect", choices=list(EFFECTS))
    s.add_argument("--color1", type=_hex)
    s.add_argument("--color2", type=_hex)
    s.add_argument("--speed", type=int)
    s.add_argument("--brightness", type=int)
    s.add_argument("--rainbow", action=argparse.BooleanOptionalAction)
    s.add_argument("--reverse", action=argparse.BooleanOptionalAction)
    s.add_argument("--temp-source", choices=["cpu", "gpu", "max"])
    sub.add_parser("off", help="turn lights off")
    p = sub.add_parser("profile", help="apply a saved profile")
    p.add_argument("name")
    sub.add_parser("profiles", help="list saved profiles")
    sub.add_parser("status", help="show current settings")
    su = sub.add_parser("setup", help="guided setup: find devices, map fan headers, count LEDs")
    su.add_argument("--auto", action="store_true", help="accept all defaults (no questions)")
    a = ap.parse_args(argv)

    if a.cmd == "setup":
        owner = _lock_owner() if _instance_running() else None
        if owner:
            print("Pausing the running RGB Control while setup runs…")
            os.kill(owner[0], signal.SIGTERM)
            for _ in range(50):
                time.sleep(0.1)
                if not _instance_running():
                    break
        from .setup_wizard import run_setup
        rc = run_setup(auto=a.auto)
        if owner:
            mode = ["--headless"] if owner[1] == "headless" else []
            subprocess.Popen([str(PROJECT_DIR / "bin" / "rgbctl"), *mode], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
            print("RGB Control restarted.")
        return rc

    if a.cmd == "effects":
        for k, cls in EFFECTS.items():
            print(f"  {k:13s} {cls.help}")
        return 0
    if a.cmd == "profiles":
        print("\n".join(list_profiles()) or "(none saved)")
        return 0
    if a.cmd == "status":
        st = load_state()
        print(f"effect: {st['effect']}")
        for k, v in st["params"].items():
            print(f"  {k}: {v}")
        print("running:", "yes" if _instance_running() else "no")
        return 0
    if a.cmd in ("set", "off", "profile"):
        st = load_state()
        if a.cmd == "off":
            st["effect"] = "off"
        elif a.cmd == "profile":
            if a.name not in list_profiles():
                print(f"No profile '{a.name}'. Saved: {', '.join(list_profiles()) or 'none'}")
                return 1
            st = load_profile(a.name, st)
        else:
            st["effect"] = a.effect
            for k in ("color1", "color2", "speed", "brightness", "rainbow", "reverse"):
                v = getattr(a, k)
                if v is not None:
                    st["params"][k] = v
            if a.temp_source:
                st["params"]["temp_source"] = a.temp_source
        save_state(st)
        _ensure_running()
        return 0

    if a.headless:
        return run_headless()
    return _start_gui(a.tray)


if __name__ == "__main__":
    sys.exit(main())
