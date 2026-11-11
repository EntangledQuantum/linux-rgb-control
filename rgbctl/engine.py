"""Render loop: runs the active effect on one clock and pushes frames to every device."""
from __future__ import annotations

import copy
import threading
import time

from openrgb.utils import DeviceType, RGBColor

from .backend import Backend, Layout, is_header
from .effects import EFFECTS, Ctx, hex_to_rgb, speed_to_rate
from .sensors import Audio, InputEvents, Temps

# Slowest devices get a frame-rate cap so they don't fall behind (GPU is on I2C).
MAX_FPS_BY_TYPE = {DeviceType.GPU: 20}
KEEPALIVE_S = 2.0  # resend unchanged frames so lights recover after sleep/resets


class Engine(threading.Thread):
    def __init__(self, state: dict, log=print):
        super().__init__(daemon=True)
        self.log = log
        self.backend = Backend(log)
        self._lock = threading.Lock()
        self._state = copy.deepcopy(state)
        self._dirty_layout = True
        self._stop = threading.Event()
        self.temps = Temps()
        self.audio = Audio()
        self.inp = InputEvents()
        self.effect = None
        self.effect_key = None
        self.layout: Layout | None = None
        self.enabled_devs: list[int] = []
        self.preview: list[tuple] = []   # last painted colors, for the GUI
        self.status = "Starting…"
        self.connected = False
        self._sent: dict[int, list] = {}
        self._identify = None       # (dev index, first LED, count, until)
        self._identify_req = None
        self._sent_at: dict[int, float] = {}

    # ---- control from other threads ------------------------------------------
    def update_state(self, state: dict) -> None:
        with self._lock:
            layout_keys = ("zones", "devices", "leds_per_fan")
            if any(state.get(k) != self._state.get(k) for k in layout_keys):
                self._dirty_layout = True
            self._state = copy.deepcopy(state)

    def relayout(self) -> None:
        with self._lock:
            self._dirty_layout = True

    def stop(self) -> None:
        self._stop.set()

    def device_names(self) -> list[tuple[str, list[tuple[str, bool]], str]]:
        """[(device name, [(zone name, is fan header)], device type)]"""
        out = []
        for d in self.backend.devices:
            zones = [(z.name, is_header(d, zi)) for zi, z in enumerate(d.zones)
                     if len(z.leds) or is_header(d, zi)]
            out.append((d.name, zones, d.type.name.title()))
        return out

    def identify(self, dev_name: str, zone_name: str, seconds: float = 4.0) -> None:
        """Blink one zone white so you can see which fans are on it."""
        with self._lock:
            self._identify_req = (dev_name, zone_name, seconds)

    # ---- loop -----------------------------------------------------------------
    def _connect(self) -> None:
        self.status = "Connecting to OpenRGB…"
        self.backend.connect()
        self.connected = True
        self._dirty_layout = True
        self.status = f"Connected: {len(self.backend.devices)} devices"

    def _rebuild(self, state: dict) -> None:
        self.layout, self.enabled_devs = self.backend.build_layout(state)
        self.backend.set_direct(self.enabled_devs)
        self._sent.clear()
        if self.effect:
            self.effect.reset(len(self.layout.leds))
        self.log(f"Layout: {len(self.layout.leds)} LEDs across {self.layout.units} fans/fixtures")

    def _start_identify(self, dev_name: str, zone_name: str, seconds: float) -> None:
        devs = self.backend.devices
        for di, d in enumerate(devs):
            if d.name != dev_name:
                continue
            for zi, z in enumerate(d.zones):
                if z.name != zone_name:
                    continue
                if is_header(d, zi) and len(z.leds) == 0:
                    # An unsized header: give it plenty of LEDs so anything plugged in lights up.
                    self.backend.resize_header(d, zi, 64)
                    time.sleep(0.2)
                    self.backend.client.update()
                    self._rebuild(self._state)
                    d = self.backend.devices[di]
                start = sum(len(zz.leds) for zz in d.zones[:zi])
                n = len(d.zones[zi].leds)
                self._identify = (di, start, n, time.monotonic() + seconds)
                if di not in self.enabled_devs:
                    self.log(f"{dev_name} is switched off in rgbctl; enable it to identify zones")
                return

    def run(self) -> None:
        phase = 0.0
        t0 = time.monotonic()
        last = t0
        wall_last = time.time()
        while not self._stop.is_set():
            try:
                if not self.connected:
                    self._connect()
                with self._lock:
                    state = self._state
                    rebuild = self._dirty_layout
                    self._dirty_layout = False
                    ident, self._identify_req = self._identify_req, None
                if rebuild:
                    self._rebuild(state)
                if ident:
                    self._start_identify(*ident)

                now = time.monotonic()
                dt = min(0.25, now - last)
                last = now
                # CLOCK_MONOTONIC stops during suspend; wall time doesn't. A gap
                # means we just woke up and the controllers have reset.
                wall = time.time()
                if (wall - wall_last) - dt > 3.0:
                    self.log("Resume from sleep detected; re-initialising devices")
                    self._rebuild(state)
                wall_last = wall

                self._frame(state, phase, now - t0, dt)
                p = state["params"]
                direction = -1.0 if p.get("reverse") else 1.0
                phase += dt * speed_to_rate(p.get("speed", 50)) * direction

                fps = max(5, min(60, int(state.get("fps", 30))))
                time.sleep(max(0.0, 1.0 / fps - (time.monotonic() - now)))
            except Exception as e:  # noqa: BLE001 - lost server, device error, etc.
                self.connected = False
                self.status = f"Disconnected ({e.__class__.__name__}): retrying…"
                self.log(f"Engine error: {e!r}")
                self.backend.close()
                self._stop.wait(3.0)
        self.audio.stop()
        self.inp.stop()

    def _frame(self, state: dict, phase: float, t: float, dt: float) -> None:
        key = state["effect"] if state["effect"] in EFFECTS else "static"
        if key != self.effect_key:
            self.effect = EFFECTS[key]()
            self.effect.reset(len(self.layout.leds))
            self.effect_key = key
            (self.audio.start if key.startswith("music") else self.audio.stop)()
            (self.inp.start if self.effect.needs_input else self.inp.stop)()

        p = state["params"]
        self.audio.gain = 0.4 + max(0, min(100, p.get("sensitivity", 50))) / 100.0 * 1.6
        self.audio.cfg = p
        ctx = Ctx(phase=phase, t=t, dt=dt, c1=hex_to_rgb(p["color1"]), c2=hex_to_rgb(p["color2"]),
                  p=p, units=self.layout.units, temps=self.temps, audio=self.audio,
                  lpf=max(1, int(state.get("leds_per_fan", 8))), inp=self.inp)
        colors = self.effect.render(ctx, self.layout.leds)
        bright = max(0, min(100, p.get("brightness", 100))) / 100.0
        self.preview = [(c[0] * bright, c[1] * bright, c[2] * bright) for c in colors]

        # Assemble one full color list per device.
        frames: dict[int, list] = {}
        devs = self.backend.devices
        for di in self.enabled_devs:
            frames[di] = [(0, 0, 0)] * len(devs[di].leds)
        for led, c in zip(self.layout.leds, self.preview):
            frames[led.dev][led.idx] = (_q(c[0]), _q(c[1]), _q(c[2]))
        # LEDs in disabled zones stay black (already black by default).

        now = time.monotonic()
        if self._identify and now < self._identify[3]:
            di, start, n = self._identify[:3]
            if di in frames:
                on = int(now * 4) % 2 == 0
                for k in range(start, min(start + n, len(frames[di]))):
                    frames[di][k] = (255, 255, 255) if on else (0, 0, 0)
        for di, frame in frames.items():
            dev = devs[di]
            min_gap = 1.0 / MAX_FPS_BY_TYPE.get(dev.type, 1000)
            last_at = self._sent_at.get(di, 0.0)
            changed = frame != self._sent.get(di)
            if (changed and now - last_at >= min_gap) or now - last_at >= KEEPALIVE_S:
                dev.set_colors([RGBColor(*c) for c in frame], fast=True)
                self._sent[di] = frame
                self._sent_at[di] = now


def _q(v: float) -> int:
    return 0 if v <= 0 else 255 if v >= 1 else int(v * 255 + 0.5)
