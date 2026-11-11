"""OpenRGB connection, server management, and the LED layout used by effects."""
from __future__ import annotations

import ctypes.util
import os
import random
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from openrgb import OpenRGBClient
from openrgb.utils import DeviceType

from .config import CONFIG_DIR, OPENRGB_HOST, OPENRGB_PORT, PROJECT_DIR

DATA_DIR = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "rgbctl"
MANAGED_OPENRGB = DATA_DIR / "OpenRGB.AppImage"


def find_openrgb() -> str | None:
    """The OpenRGB binary to run: $RGBCTL_OPENRGB, the installer's copy, a vendored one, or PATH."""
    env = os.environ.get("RGBCTL_OPENRGB")
    if env and os.access(env, os.X_OK):
        return env
    for p in (MANAGED_OPENRGB, PROJECT_DIR / "vendor" / "openrgb" / "OpenRGB.AppImage"):
        if os.access(p, os.X_OK):
            return str(p)
    return shutil.which("openrgb") or shutil.which("OpenRGB")


def openrgb_env(exe: str) -> dict:
    env = dict(os.environ)
    # AppImages need FUSE 2; without it they can still run by self-extracting.
    if exe.endswith(".AppImage") and not ctypes.util.find_library("fuse"):
        env["APPIMAGE_EXTRACT_AND_RUN"] = "1"
    return env


def port_open(host=OPENRGB_HOST, port=OPENRGB_PORT) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.3):
            return True
    except OSError:
        return False


def zone_limits(dev, zi: int) -> tuple[int, int]:
    try:
        zd = dev.data.zones[zi]
        return int(zd.leds_min), int(zd.leds_max)
    except Exception:  # noqa: BLE001
        n = len(dev.zones[zi].leds)
        return n, n


def is_header(dev, zi: int) -> bool:
    """An addressable header (ARGB fan / strip connector): a linear zone you can resize."""
    lo, hi = zone_limits(dev, zi)
    return hi > lo and dev.zones[zi].type.name == "LINEAR"


def zone_key(dev, zone) -> str:
    return f"{dev.name}::{zone.name}"


TYPE_SHORT = {DeviceType.GPU: "GPU", DeviceType.MOTHERBOARD: "Board", DeviceType.KEYBOARD: "Keyboard",
              DeviceType.MOUSE: "Mouse", DeviceType.DRAM: "RAM", DeviceType.COOLER: "Cooler",
              DeviceType.LEDSTRIP: "Strip", DeviceType.HEADSET: "Headset", DeviceType.MOUSEMAT: "Mousepad"}
TYPE_RANK = [DeviceType.MOTHERBOARD, DeviceType.COOLER, DeviceType.LEDSTRIP, DeviceType.DRAM,
             DeviceType.GPU, DeviceType.MOUSE, DeviceType.MOUSEMAT, DeviceType.KEYBOARD]
KIND = {DeviceType.GPU: "gpu", DeviceType.MOUSE: "mouse", DeviceType.KEYBOARD: "keyboard",
        DeviceType.DRAM: "ram"}
GPU_ORDER = ["Left fan", "Center fan", "Right fan"]


@dataclass
class Led:
    dev: int          # index into Backend.devices
    idx: int          # LED index inside the device
    pos: float        # 0..1 position along the whole rig (for waves, comets)
    unit: int         # which fan / fixture this LED belongs to (global numbering)
    local: float      # 0..1 position inside its fan (for spin effects)
    ring: int = 1     # how many LEDs share this fan/fixture
    kind: str = ""    # "fan" (header fan), "gpu", "board", "ram", "mouse", "keyboard"
    rnd: float = field(default_factory=random.random)


@dataclass
class Layout:
    leds: list[Led]               # LEDs that effects paint
    black: list[tuple[int, int]]  # (dev, idx) LEDs in disabled zones, held off
    units: int
    unit_names: list[str]


class Backend:
    def __init__(self, log=print):
        self.log = log
        self.client: OpenRGBClient | None = None
        self.server_proc: subprocess.Popen | None = None

    # ---- server / connection -------------------------------------------------
    def ensure_server(self, timeout=60) -> None:
        if port_open():
            return
        exe = find_openrgb()
        if not exe:
            raise RuntimeError("OpenRGB not found. Run ./install.sh, or set RGBCTL_OPENRGB to the OpenRGB binary.")
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        logf = open(CONFIG_DIR / "openrgb-server.log", "ab")
        self.log(f"Starting OpenRGB server: {exe}")
        self.server_proc = subprocess.Popen(
            [exe, "--server", "--noautoconnect", "--server-host", OPENRGB_HOST, "--server-port", str(OPENRGB_PORT)],
            stdout=logf, stderr=logf, stdin=subprocess.DEVNULL, start_new_session=True, env=openrgb_env(exe))
        end = time.time() + timeout
        while time.time() < end:
            if self.server_proc.poll() is not None:
                raise RuntimeError("OpenRGB server exited; see ~/.config/rgbctl/openrgb-server.log")
            if port_open():
                return
            time.sleep(0.5)
        raise RuntimeError("OpenRGB server did not start in time")

    def connect(self, wait_devices: float = 30) -> None:
        self.ensure_server()
        last_err = None
        end = time.time() + wait_devices
        # Device detection on the server takes a few seconds after the port opens.
        while time.time() < end:
            try:
                if self.client is None:
                    self.client = OpenRGBClient(OPENRGB_HOST, OPENRGB_PORT, "rgbctl")
                self.client.update()
                if self.client.devices:
                    time.sleep(1.0)       # let late detectors finish
                    self.client.update()
                    break
            except Exception as e:  # noqa: BLE001 - server still starting
                last_err = e
                self.client = None
            time.sleep(1)
        if self.client is None:
            raise RuntimeError(f"Could not connect to OpenRGB: {last_err}")
        self.log(f"Connected to OpenRGB: {len(self.devices)} devices")

    def close(self, stop_server=False) -> None:
        try:
            if self.client:
                self.client.disconnect()
        except Exception:  # noqa: BLE001
            pass
        self.client = None
        if stop_server and self.server_proc and self.server_proc.poll() is None:
            self.server_proc.terminate()

    @property
    def devices(self):
        return self.client.devices if self.client else []

    def short_names(self) -> list[str]:
        """Friendly names: 'GPU', 'Board', 'Keyboard', or 'RAM 2' when there are several."""
        base = [TYPE_SHORT.get(d.type, d.name) for d in self.devices]
        out = []
        for i, b in enumerate(base):
            same = [j for j, x in enumerate(base) if x == b]
            out.append(b if len(same) == 1 else f"{b} {same.index(i) + 1}")
        return out

    def set_direct(self, enabled_devs: list[int]) -> None:
        for i in enabled_devs:
            dev = self.devices[i]
            try:
                dev.set_mode("direct")
            except Exception as e:  # noqa: BLE001
                self.log(f"{dev.name}: could not set direct mode: {e}")

    def resize_header(self, dev, zi: int, size: int) -> bool:
        lo, hi = zone_limits(dev, zi)
        size = max(lo, min(hi, size))
        if len(dev.zones[zi].leds) == size:
            return False
        dev.zones[zi].resize(size)
        return True

    def sync_header_sizes(self, state: dict) -> None:
        """Size each configured fan header to fans × LEDs-per-fan, so OpenRGB drives exactly
        the LEDs that exist."""
        lpf = max(1, int(state.get("leds_per_fan", 8)))
        changed = False
        for dev in self.devices:
            if not state.get("devices", {}).get(dev.name, True):
                continue
            for zi, z in enumerate(dev.zones):
                if not is_header(dev, zi):
                    continue
                cfg = state.get("zones", {}).get(zone_key(dev, z))
                if not cfg or not cfg.get("enabled", False):
                    continue
                changed |= self.resize_header(dev, zi, max(1, int(cfg.get("fans", 1))) * lpf)
        if changed:
            time.sleep(0.3)
            self.client.update()

    # ---- layout ----------------------------------------------------------------
    def build_layout(self, state: dict) -> tuple[Layout, list[int]]:
        self.sync_header_sizes(state)
        lpf = max(1, int(state.get("leds_per_fan", 8)))
        zcfg = state.get("zones", {})
        dcfg = state.get("devices", {})
        shorts = self.short_names()

        fixtures = []  # (rank, dev_i, zone_i, zone, start_idx, zone_cfg, header?)
        black = []
        enabled_devs = []
        for di, dev in enumerate(self.devices):
            if not dcfg.get(dev.name, True):
                continue
            enabled_devs.append(di)
            trank = TYPE_RANK.index(dev.type) if dev.type in TYPE_RANK else len(TYPE_RANK)
            start = 0
            for zi, z in enumerate(dev.zones):
                n = len(z.leds)
                hdr = is_header(dev, zi)
                cfg = zcfg.get(zone_key(dev, z))
                # Headers nobody configured are unknown (often empty), so they start off.
                enabled = cfg.get("enabled", True) if cfg else not hdr
                if n and enabled:
                    zrank = GPU_ORDER.index(z.name) if z.name in GPU_ORDER else 10 + zi
                    fixtures.append(((trank, di, zrank), di, zi, z, start, cfg or {}, hdr))
                else:
                    black.extend((di, start + k) for k in range(n))
                start += n
        fixtures.sort(key=lambda f: f[0])

        # Each fixture gets a number of "slots" along the rig.
        planned = []
        for _rank, di, zi, z, start, cfg, hdr in fixtures:
            dev = self.devices[di]
            n = len(z.leds)
            if hdr:
                planned.append((di, z, start, n, max(1, int(cfg.get("fans", 1))), "fans"))
            elif dev.type == DeviceType.KEYBOARD:
                planned.append((di, z, start, n, 3, "span"))
            else:
                planned.append((di, z, start, n, 1, "span"))
        total = sum(p[4] for p in planned) or 1

        leds: list[Led] = []
        names: list[str] = []
        slot = 0
        unit = 0
        for di, z, start, n, slots, kind in planned:
            dev = self.devices[di]
            if kind == "fans":
                for k in range(n):
                    if k >= slots * lpf:
                        black.append((di, start + k))
                        continue
                    f = k // lpf
                    leds.append(Led(di, start + k, (slot + f + 0.5) / total, unit + f, (k % lpf) / lpf,
                                    ring=lpf, kind="fan"))
                label = zcfg.get(zone_key(dev, z), {}).get("label") or z.name
                names += [f"{label} · fan {f + 1}" if slots > 1 else label for f in range(slots)]
                unit += slots
            else:
                xs = _local_x(z, n)
                k_ = KIND.get(dev.type, "board")
                for k in range(n):
                    leds.append(Led(di, start + k, (slot + xs[k] * slots) / total, unit, xs[k],
                                    ring=n, kind=k_))
                short = shorts[di]
                names.append(short if z.name.lower() == short.lower() or len(dev.zones) == 1
                             else f"{short} {z.name}")
                unit += 1
            slot += slots
        return Layout(leds, black, unit, names), enabled_devs


def _local_x(zone, n: int) -> list[float]:
    """Horizontal 0..1 position of each LED in a zone (uses the key matrix if any)."""
    xs = [(k + 0.5) / n for k in range(n)]
    mm = getattr(zone, "matrix_map", None)
    if mm:
        width = max((len(r) for r in mm), default=0)
        if width > 1:
            for row in mm:
                for col, led in enumerate(row):
                    if led is not None and 0 <= led < n:
                        xs[led] = col / (width - 1)
    return xs
