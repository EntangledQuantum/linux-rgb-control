"""Inputs for reactive effects: CPU/GPU temperature and system audio level."""
from __future__ import annotations

import shutil
import subprocess
import threading
import time
from pathlib import Path


def _find_cpu_temp_file() -> Path | None:
    for h in Path("/sys/class/hwmon").glob("hwmon*"):
        try:
            if (h / "name").read_text().strip() in ("k10temp", "coretemp", "zenpower"):
                return h / "temp1_input"
        except OSError:
            continue
    return None


class Temps:
    """Polls CPU and GPU temperature at most once a second."""

    def __init__(self):
        self.cpu_file = _find_cpu_temp_file()
        self._nvml = None
        self._last = 0.0
        self.cpu = 0.0
        self.gpu = 0.0

    def _gpu_temp(self) -> float:
        try:
            if self._nvml is None:
                import pynvml
                pynvml.nvmlInit()
                self._nvml = (pynvml, pynvml.nvmlDeviceGetHandleByIndex(0))
            nv, h = self._nvml
            return float(nv.nvmlDeviceGetTemperature(h, nv.NVML_TEMPERATURE_GPU))
        except Exception:  # noqa: BLE001
            return 0.0

    cpu_load = 0.0   # 0..1
    gpu_load = 0.0   # 0..1
    ram = 0.0        # 0..1

    def poll(self) -> None:
        now = time.monotonic()
        if now - self._last < 1.0:
            return
        self._last = now
        if self.cpu_file:
            try:
                self.cpu = int(self.cpu_file.read_text()) / 1000.0
            except (OSError, ValueError):
                pass
        self.gpu = self._gpu_temp()
        try:
            import psutil
            self.cpu_load = psutil.cpu_percent(interval=None) / 100.0
            self.ram = psutil.virtual_memory().percent / 100.0
        except Exception:  # noqa: BLE001
            pass
        if self._nvml:
            try:
                nv, h = self._nvml
                self.gpu_load = nv.nvmlDeviceGetUtilizationRates(h).gpu / 100.0
            except Exception:  # noqa: BLE001
                pass


class Audio:
    """Captures what the speakers play (the default output's monitor) and analyses it:
    overall level, bass/mid/treble, a log-spaced spectrum, and beat detection."""

    RATE = 22050
    HOP = 512          # samples per read, ~23 ms → ~43 analyses per second
    WIN = 2048         # FFT window
    NBANDS = 16

    def __init__(self):
        self.level = 0.0      # smoothed overall loudness 0..1
        self.peak = 0.0       # fast attack/decay
        self.bass = self.mid = self.treble = 0.0
        self.bands = [0.0] * self.NBANDS   # low → high frequency, each 0..1
        self.beats = 0                     # increments on every detected beat
        self.beat_at = 0.0                 # monotonic time of last beat
        self.gain = 1.0                    # overall sensitivity multiplier
        self.cfg: dict = {}                # live tuning (effect params dict)
        self._proc = None
        self._thread = None
        self._stop = threading.Event()
        self.available = shutil.which("parec") is not None

    def start(self) -> None:
        if self._thread or not self.available:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._proc:
            self._proc.kill()
        self._thread = None
        self._proc = None
        self.level = self.peak = self.bass = self.mid = self.treble = 0.0
        self.bands = [0.0] * self.NBANDS

    def _run(self) -> None:
        import numpy as np

        try:
            self._proc = subprocess.Popen(
                ["parec", "--device=@DEFAULT_MONITOR@", "--format=s16le", f"--rate={self.RATE}",
                 "--channels=1", "--latency-msec=20"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        except OSError:
            return

        freqs = np.fft.rfftfreq(self.WIN, 1.0 / self.RATE)
        window = np.hanning(self.WIN).astype(np.float32)
        edges = np.geomspace(35, 10000, self.NBANDS + 1)
        band_idx = [np.where((freqs >= lo) & (freqs < hi))[0] for lo, hi in zip(edges[:-1], edges[1:])]
        band_idx = [ix if len(ix) else np.array([np.argmin(abs(freqs - lo))])
                    for ix, lo in zip(band_idx, edges[:-1])]
        cutoff = None
        groups = {}

        def gain_of(key):   # slider 0..100 → ×0.25 … ×4 (50 = ×1)
            return 2.0 ** ((float(self.cfg.get(key, 50)) - 50) / 25)

        ring = np.zeros(self.WIN, dtype=np.float32)
        # Adaptive ceilings: each value is normalised against a slowly decaying recent max,
        # so quiet and loud music both use the full 0..1 range.
        ceil = {"level": 1e-3, "bass": 1e-3, "mid": 1e-3, "treble": 1e-3}
        band_ceil = np.full(self.NBANDS, 1e-3)
        bass_hist = []
        nbytes = self.HOP * 2
        while not self._stop.is_set():
            buf = self._proc.stdout.read(nbytes)
            if not buf or len(buf) < nbytes:
                break
            x = np.frombuffer(buf, dtype=np.int16).astype(np.float32) / 32768.0
            ring = np.roll(ring, -self.HOP)
            ring[-self.HOP:] = x
            spec = np.abs(np.fft.rfft(ring * window))
            cfg = self.cfg

            want = float(cfg.get("bass_cutoff", 160))
            if want != cutoff:   # bass/mid split point changed
                cutoff = want
                groups = {"bass": (freqs >= 25) & (freqs < cutoff),
                          "mid": (freqs >= cutoff) & (freqs < 2000),
                          "treble": (freqs >= 2000) & (freqs < 10000)}

            g = self.gain
            rms = float(np.sqrt(np.mean(x * x)))
            gate = (float(cfg.get("noise_gate", 10)) / 100) ** 2 * 0.05
            silent = rms < gate
            vals = {"level": rms}
            for k, m in groups.items():
                vals[k] = float(np.mean(spec[m]))
            gains = {"level": g, "bass": g * gain_of("bass_gain"), "mid": g * gain_of("mid_gain"),
                     "treble": g * gain_of("treble_gain")}
            out = {}
            for k, v in vals.items():
                ceil[k] = max(v, ceil[k] * 0.9985, 1e-4)
                out[k] = 0.0 if silent or v < ceil[k] * 0.02 else min(1.0, v / ceil[k] * gains[k])
            bands = np.array([spec[ix].mean() for ix in band_idx])
            band_ceil = np.maximum(bands, band_ceil * 0.998)
            bnorm = np.clip(bands / np.maximum(band_ceil, 1e-4) * g, 0, 1)
            bnorm[bands < band_ceil * 0.03] = 0.0
            if silent:
                bnorm[:] = 0.0

            # Smoothing: fast attack; the release gets slower as the smoothing slider rises.
            down = 0.5 - float(cfg.get("smoothing", 50)) / 100 * 0.45

            def sm(old, new, up=0.7):
                return old + (new - old) * (up if new > old else down)

            self.level = sm(self.level, out["level"])
            self.bass = sm(self.bass, out["bass"], 0.85)
            self.mid = sm(self.mid, out["mid"])
            self.treble = sm(self.treble, out["treble"])
            self.bands = [sm(o, float(n)) for o, n in zip(self.bands, bnorm)]
            self.peak = out["level"] if out["level"] > self.peak else self.peak * 0.85

            # Beat: bass energy jumps well above its recent average. The threshold slider sets
            # how big the jump must be (1.15× … 2.15× the last second's average).
            e = vals["bass"]
            bass_hist.append(e)
            if len(bass_hist) > 43:          # ~1 s of history
                bass_hist.pop(0)
            avg = sum(bass_hist) / len(bass_hist)
            ratio = 1.15 + float(cfg.get("beat_threshold", 30)) / 100.0
            gap = float(cfg.get("beat_gap", 220)) / 1000.0
            now = time.monotonic()
            if (not silent and len(bass_hist) > 10 and e > avg * ratio and out["bass"] > 0.3
                    and now - self.beat_at > gap):
                self.beats += 1
                self.beat_at = now


class InputEvents:
    """Counts mouse-wheel ticks, clicks and keypresses system-wide (X11 RECORD extension).

    Only counts are kept: which key was pressed is never read or stored. Runs only
    while an input-reactive effect is selected. Not available on Wayland sessions."""

    def __init__(self):
        self.scroll = 0           # net wheel ticks (+1 up, -1 down)
        self.scroll_at = 0.0      # monotonic time of last tick
        self.clicks = 0
        self.click_button = 0     # 1 left, 2 middle, 3 right
        self.click_at = 0.0
        self.keys = 0
        self.key_at = 0.0
        self.error = ""
        self._thread = None
        self._ctx = None
        self._ctrl = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    _qdisp = None
    _key_times: list = []

    def pointer(self) -> tuple[float, float]:
        """Mouse position as 0..1 fractions of the whole screen. Call from one thread only
        (the engine's): it keeps its own X connection."""
        try:
            if self._qdisp is None:
                from Xlib import display
                self._qdisp = display.Display()
                self._root = self._qdisp.screen().root
                g = self._root.get_geometry()
                self._sw, self._sh = max(1, g.width), max(1, g.height)
            q = self._root.query_pointer()
            return q.root_x / self._sw, q.root_y / self._sh
        except Exception:  # noqa: BLE001
            return 0.5, 0.5

    def typing_speed(self) -> float:
        """Keys per second over the last 3 seconds."""
        now = time.monotonic()
        return sum(1 for t in self._key_times if now - t < 3.0) / 3.0

    def start(self) -> None:
        if self.running:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._ctrl is not None and self._ctx is not None:
            try:
                self._ctrl.record_disable_context(self._ctx)
                self._ctrl.flush()
            except Exception:  # noqa: BLE001
                pass
        self._thread = None

    def _run(self) -> None:
        try:
            from Xlib import X, display
            from Xlib.ext import record
            from Xlib.protocol import rq
        except ImportError:
            self.error = "python-xlib not installed"
            return
        try:
            self._ctrl = display.Display()
            rec = display.Display()
            if not rec.has_extension("RECORD"):
                self.error = "X RECORD extension missing"
                return
            self._ctx = rec.record_create_context(0, [record.AllClients], [{
                "core_requests": (0, 0), "core_replies": (0, 0),
                "ext_requests": (0, 0, 0, 0), "ext_replies": (0, 0, 0, 0),
                "delivered_events": (0, 0), "device_events": (X.KeyPress, X.ButtonPress),
                "errors": (0, 0), "client_started": False, "client_died": False}])
        except Exception as e:  # noqa: BLE001 - no X display (e.g. Wayland/headless)
            self.error = f"input capture unavailable: {e}"
            return

        field = rq.EventField(None)

        def cb(reply):
            if reply.category != record.FromServer or reply.client_swapped or not reply.data:
                return
            data = reply.data
            while data:
                ev, data = field.parse_binary_value(data, rec.display, None, None)
                now = time.monotonic()
                if ev.type == X.ButtonPress:
                    if ev.detail in (4, 5):
                        self.scroll += 1 if ev.detail == 4 else -1
                        self.scroll_at = now
                    elif ev.detail in (1, 2, 3):
                        self.clicks += 1
                        self.click_button = ev.detail
                        self.click_at = now
                elif ev.type == X.KeyPress:
                    self.keys += 1        # count only; the key itself is ignored
                    self.key_at = now
                    self._key_times = [t for t in self._key_times if now - t < 3.0] + [now]

        try:
            rec.record_enable_context(self._ctx, cb)   # blocks until stop()
            rec.record_free_context(self._ctx)
        except Exception as e:  # noqa: BLE001
            self.error = str(e)
        finally:
            self._ctx = None
