"""Interactive first-run setup: discover devices, map fan headers, count LEDs per fan."""
from __future__ import annotations

import sys
import time

from openrgb.utils import RGBColor

from . import autostart
from .backend import Backend, is_header, zone_key
from .config import load_state, save_state

_TTY = sys.stdout.isatty()
B, DIM, G, Y, R = (("\033[1m", "\033[2m", "\033[32m", "\033[33m", "\033[0m") if _TTY
                   else ("", "", "", "", ""))
BLOCKS = [("red", (255, 0, 0), "\033[41m"), ("green", (0, 255, 0), "\033[42m"),
          ("blue", (0, 0, 255), "\033[44m"), ("yellow", (255, 255, 0), "\033[43m"),
          ("magenta", (255, 0, 255), "\033[45m"), ("cyan", (0, 255, 255), "\033[46m")]


def ask(prompt: str, default: str, auto: bool) -> str:
    if auto:
        print(f"{prompt} {DIM}[{default}]{R} {default}")
        return default
    try:
        v = input(f"{prompt} {DIM}[{default}]{R} ").strip()
    except EOFError:
        v = ""
    return v or default


def yes(prompt: str, default: bool, auto: bool) -> bool:
    v = ask(prompt + (" (Y/n)" if default else " (y/N)"), "y" if default else "n", auto)
    return v.lower().startswith("y")


def ask_int(prompt: str, default: int, lo: int, hi: int, auto: bool) -> int:
    while True:
        v = ask(prompt, str(default), auto)
        try:
            n = int(v)
            if lo <= n <= hi:
                return n
        except ValueError:
            pass
        print(f"  Please enter a number from {lo} to {hi}.")


def step(n: int, total: int, title: str) -> None:
    print(f"\n{B}Step {n}/{total} · {title}{R}")


class Painter:
    """Direct LED writes for the wizard: everything off except what we're showing."""

    def __init__(self, be: Backend, devs: list[int]):
        self.be = be
        self.devs = devs
        be.set_direct(devs)

    def blank(self) -> None:
        for di in self.devs:
            d = self.be.devices[di]
            d.set_colors([RGBColor(0, 0, 0)] * len(d.leds))

    def zone(self, di: int, zi: int, colors: list[tuple]) -> None:
        d = self.be.devices[di]
        start = sum(len(z.leds) for z in d.zones[:zi])
        out = [RGBColor(0, 0, 0)] * len(d.leds)
        for k, c in enumerate(colors[: len(d.zones[zi].leds)]):
            out[start + k] = RGBColor(*c)
        d.set_colors(out)


def run_setup(auto: bool = False) -> int:
    total = 5
    print(f"\n{B}✨ RGB Control setup{R}")
    print("This finds your RGB devices and works out how your fans are connected. "
          "Keep your PC's side panel in view.\n")

    step(1, total, "Looking for RGB devices")
    be = Backend(log=lambda m: print(f"  {DIM}{m}{R}"))
    try:
        be.connect(wait_devices=45)
    except Exception as e:  # noqa: BLE001
        print(f"  {Y}Couldn't talk to OpenRGB: {e}{R}")
        print("  Re-run ./install.sh, or check ~/.config/rgbctl/openrgb-server.log")
        return 1
    devs = be.devices
    if not devs:
        print(f"  {Y}No RGB devices found.{R}")
        _no_devices_help()
        return 1
    names = be.short_names()
    for i, d in enumerate(devs):
        hdrs = sum(1 for zi in range(len(d.zones)) if is_header(d, zi))
        extra = f", {hdrs} fan header{'s' if hdrs != 1 else ''}" if hdrs else ""
        print(f"  {G}✓{R} {names[i]:<10} {d.name}  {DIM}({len(d.zones)} zones{extra}){R}")
    print(f"  {DIM}Something missing? See the README's 'My device isn't detected' section.{R}")

    state = load_state()
    step(2, total, "Choose what RGB Control should control")
    enabled = []
    for i, d in enumerate(devs):
        on = yes(f"  Control {names[i]} ({d.name})?", state["devices"].get(d.name, True), auto)
        state["devices"][d.name] = on
        if on:
            enabled.append(i)
    if not enabled:
        print("  Nothing selected; you can change this later in the Devices tab.")
        save_state(state)
        return 0

    paint = Painter(be, enabled)
    paint.blank()

    step(3, total, "Map your fan headers")
    headers = [(di, zi) for di in enabled for zi in range(len(devs[di].zones)) if is_header(devs[di], zi)]
    used = []
    if not headers:
        print("  No addressable fan headers on the selected devices. That's fine: skipping.")
    for di, zi in headers:
        d = be.devices[di]
        z = d.zones[zi]
        if len(z.leds) < 64:
            be.resize_header(d, zi, 64)
            time.sleep(0.2)
            be.client.update()
            paint.blank()
            d = be.devices[di]
        paint.zone(di, zi, [(255, 255, 255)] * 64)
        key = zone_key(d, d.zones[zi])
        old = state["zones"].get(key, {})
        print(f"\n  Header {B}{z.name}{R} on {names[di]} is now lit {B}WHITE{R}.")
        fans = ask_int("  How many fans (or strips) light up? 0 = nothing / not in use",
                       int(old.get("fans", 0)) if old.get("enabled") else 0, 0, 12, auto)
        if fans:
            label = ask("  Give it a name, e.g. 'Front fans'", old.get("label", f"{z.name}"), auto)
            state["zones"][key] = {"enabled": True, "fans": fans, "label": label}
            used.append((di, zi, fans))
        else:
            state["zones"][key] = {"enabled": False, "fans": 1, "label": old.get("label", "")}
            be.resize_header(d, zi, 0)
            time.sleep(0.2)
            be.client.update()
        paint.blank()

    step(4, total, "Count the LEDs in one fan")
    if used:
        di, zi, _ = used[0]
        colors = []
        for _, rgb, _ in BLOCKS:
            colors += [rgb] * 4
        colors += [(255, 255, 255)] * 40
        paint.zone(di, zi, colors)
        legend = "  ".join((f"{ansi}  {R} " if _TTY else "") + name for name, _, ansi in BLOCKS) + "  then white"
        print(f"  The first fan on {B}{be.devices[di].zones[zi].name}{R} now shows blocks of 4 LEDs:")
        print(f"  {legend}")
        print("  Example: red + green only → 8 LEDs.  red, green, blue → 12.  four colors → 16.")
        state["leds_per_fan"] = ask_int("  How many LEDs does one fan have?",
                                        int(state.get("leds_per_fan", 8)), 1, 60, auto)
        paint.blank()
    else:
        print("  Skipped (no fan headers in use).")

    step(5, total, "Finish")
    save_state(state)
    print(f"  {G}✓{R} Saved to ~/.config/rgbctl/state.json")
    if yes("  Start RGB Control automatically when you log in?", True, auto):
        autostart.set_enabled(True)
        print(f"  {G}✓{R} Will start in the tray at login")
    # A little celebration: one rainbow sweep across everything.
    try:
        import colorsys
        for f in range(45):
            for di in enabled:
                d = be.devices[di]
                n = max(1, len(d.leds))
                d.set_colors([RGBColor(*[int(v * 255) for v in colorsys.hsv_to_rgb((k / n + f / 30) % 1, 1, 1)])
                              for k in range(n)], fast=True)
            time.sleep(1 / 30)
    except Exception:  # noqa: BLE001
        pass
    be.close()
    print(f"\n{B}🎉 All set!{R} Open {B}RGB Control{R} from your app menu, or run: {B}rgbctl{R}\n")
    return 0


def _no_devices_help() -> None:
    print("""  Things to check:
   • Log out and back in (or reboot) once after install, so device permissions apply.
   • Motherboard/RAM RGB over SMBus may need the kernel option acpi_enforce_resources=lax.
   • Is your device on OpenRGB's supported list? https://openrgb.org/devices.html
   • Logs: ~/.config/rgbctl/openrgb-server.log""")


if __name__ == "__main__":
    sys.exit(run_setup("--auto" in sys.argv))
