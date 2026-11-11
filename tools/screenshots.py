"""Render README / website screenshots offscreen on a demo rig (no hardware needed).

    QT_QPA_PLATFORM=offscreen .venv/bin/python tools/screenshots.py docs/screenshots
"""
from __future__ import annotations

import copy
import math
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from rgbctl import config, gui  # noqa: E402
from rgbctl.backend import Layout, Led  # noqa: E402
from rgbctl.effects import EFFECTS, Ctx, hex_to_rgb, speed_to_rate  # noqa: E402
from rgbctl.sensors import Temps  # noqa: E402

gui.save_state = config.save_state = lambda s: None   # never touch real settings


def demo_layout() -> Layout:
    leds, names, u, slot = [], [], 0, 0
    fixtures = [("Front fans", 3, "fan"), ("Rear fan", 1, "fan"), ("Top fans", 2, "fan")]
    total = 3 + 1 + 2 + 4 + 3
    for label, fans, _ in fixtures:
        for f in range(fans):
            for k in range(8):
                leds.append(Led(0, len(leds), (slot + 0.5) / total, u, k / 8, ring=8, kind="fan"))
            names.append(f"{label} {f + 1}" if fans > 1 else label)
            u += 1
            slot += 1
    for z in ("Left fan", "Center fan", "Right fan", "Side"):
        leds.append(Led(1, len(leds), (slot + 0.5) / total, u, 0.5, ring=1, kind="gpu"))
        names.append(f"GPU {z}")
        u += 1
        slot += 1
    for k in range(66):
        x = (k % 22) / 21
        leds.append(Led(2, len(leds), (slot + x * 3) / total, u, x, ring=66, kind="keyboard"))
    names.append("Keyboard")
    u += 1
    return Layout(leds, [], u, names)


class FakeAudio:
    available = True

    def __init__(self):
        self.t = 0.0
        self.beats = 0
        self.beat_at = 0.0
        self.bands = [0.0] * 16
        self.bass = self.mid = self.treble = self.level = self.peak = 0.0

    def tick(self, dt):
        self.t += dt
        kick = math.exp(-((self.t * 2.1) % 1.0) * 6)
        if (self.t * 2.1) % 1.0 < dt * 2.1:
            self.beats += 1
            self.beat_at = time.monotonic()
        self.bass = 0.35 + 0.6 * kick
        self.mid = 0.45 + 0.25 * math.sin(self.t * 3.3)
        self.treble = 0.3 + 0.2 * math.sin(self.t * 7.1)
        self.level = self.peak = 0.5 + 0.4 * kick
        self.bands = [max(0.05, min(1, (0.95 - i * 0.045) * (0.55 + 0.45 * kick if i < 4 else
                      0.6 + 0.35 * math.sin(self.t * (2 + i) + i))) + random.uniform(-0.05, 0.05))
                      for i in range(16)]


class FakeInp:
    error = ""
    scroll, scroll_at, clicks, click_at, click_button, keys, key_at = 37, 0.0, 3, 0.0, 1, 0, 0.0

    def pointer(self):
        return (0.35, 0.4)

    def typing_speed(self):
        return 6.0


class FakeEngine:
    status = "Connected: 4 devices"

    def __init__(self, effect_key):
        self.layout = demo_layout()
        self.audio = FakeAudio()
        self.inp = FakeInp()
        self.temps = Temps()
        self.effect_key = effect_key
        self.effect = EFFECTS[effect_key]()
        self.effect.reset(len(self.layout.leds))
        self.preview = []

    def run(self, params, seconds):
        dt, phase, t = 1 / 30, 0.0, 0.0
        for _ in range(int(seconds * 30)):
            self.audio.tick(dt)
            t += dt
            phase += dt * speed_to_rate(params.get("speed", 50))
            ctx = Ctx(phase=phase, t=t, dt=dt, c1=hex_to_rgb(params["color1"]), c2=hex_to_rgb(params["color2"]),
                      p=params, units=self.layout.units, temps=self.temps, audio=self.audio, lpf=8, inp=self.inp)
            self.preview = self.effect.render(ctx, self.layout.leds)

    def device_names(self):
        return [("Gigabyte AORUS GeForce RTX 5090 MASTER", [("Left fan", False), ("Center fan", False),
                                                           ("Right fan", False), ("Side", False)], "Gpu"),
                ("X870E AORUS ELITE WIFI7", [("ARGB_V2_1", True), ("ARGB_V2_2", True), ("ARGB_V2_3", True),
                                             ("LED_C", False), ("Chipset Accent", False)], "Motherboard"),
                ("Razer Blackwidow V3", [("Keyboard", False)], "Keyboard")]

    def update_state(self, s):
        pass

    def identify(self, *a):
        pass


def shot(app, out: Path, effect: str, params: dict, tab: int = 0, seconds: float = 3.0):
    st = copy.deepcopy(config.DEFAULT_STATE)
    st["effect"] = effect
    st["params"].update(params)
    st["zones"] = {
        "X870E AORUS ELITE WIFI7::ARGB_V2_1": {"enabled": True, "fans": 3, "label": "Front fans"},
        "X870E AORUS ELITE WIFI7::ARGB_V2_2": {"enabled": True, "fans": 1, "label": "Rear fan"},
        "X870E AORUS ELITE WIFI7::ARGB_V2_3": {"enabled": True, "fans": 2, "label": "Top fans"},
        "X870E AORUS ELITE WIFI7::LED_C": {"enabled": False},
    }
    eng = FakeEngine(effect)
    eng.run(st["params"], seconds)
    w = gui.MainWindow(eng, st)
    w.tick.stop()
    w.resize(1120, 860)
    w.show()
    w._build_devices_tab()
    w.centralWidget().findChild(gui.QTabWidget).setCurrentIndex(tab)
    w.info.setText(eng.effect.info)
    w.info.setVisible(bool(eng.effect.info))
    for _ in range(10):
        app.processEvents()
        time.sleep(0.02)
    w.grab().save(str(out))
    print("saved", out)
    w.close()


def wizard_image(out: Path):
    lines = [
        [("✨ RGB Control setup", "#ffffff", True)],
        [("This finds your RGB devices and works out how your fans are connected.", "#9aa0ad", False)],
        [],
        [("Step 1/5 · Looking for RGB devices", "#ffffff", True)],
        [("  ✓ ", "#4ade80", False), ("GPU        Gigabyte AORUS GeForce RTX 5090 MASTER  ", "#e6e6e6", False), ("(4 zones)", "#7c8396", False)],
        [("  ✓ ", "#4ade80", False), ("Board      X870E AORUS ELITE WIFI7  ", "#e6e6e6", False), ("(5 zones, 3 fan headers)", "#7c8396", False)],
        [("  ✓ ", "#4ade80", False), ("Keyboard   Razer Blackwidow V3  ", "#e6e6e6", False), ("(1 zone)", "#7c8396", False)],
        [],
        [("Step 3/5 · Map your fan headers", "#ffffff", True)],
        [("  Header ", "#e6e6e6", False), ("ARGB_V2_1", "#ffffff", True), (" on Board is now lit ", "#e6e6e6", False), ("WHITE", "#ffffff", True), (".", "#e6e6e6", False)],
        [("  How many fans (or strips) light up? 0 = nothing / not in use ", "#e6e6e6", False), ("[0] ", "#7c8396", False), ("3", "#7dd3fc", True)],
        [("  Give it a name, e.g. 'Front fans' ", "#e6e6e6", False), ("[ARGB_V2_1] ", "#7c8396", False), ("Front fans", "#7dd3fc", True)],
        [],
        [("Step 4/5 · Count the LEDs in one fan", "#ffffff", True)],
        [("  ", "#000", False), ("██", "#ff3030", False), (" red  ", "#e6e6e6", False), ("██", "#30ff60", False), (" green  ", "#e6e6e6", False),
         ("██", "#3080ff", False), (" blue  ", "#e6e6e6", False), ("██", "#ffe030", False), (" yellow  … then white", "#e6e6e6", False)],
        [("  How many LEDs does one fan have? ", "#e6e6e6", False), ("[8] ", "#7c8396", False), ("8", "#7dd3fc", True)],
        [],
        [("🎉 All set! ", "#ffffff", True), ("Open RGB Control from your app menu, or run: ", "#e6e6e6", False), ("rgbctl", "#ffffff", True)],
    ]
    W, H, lh = 1000, 40 + len(lines) * 26 + 30, 26
    img = QImage(W, H, QImage.Format_ARGB32)
    img.fill(QColor("#0f1013"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    p.fillRect(QRectF(0, 0, W, 32), QColor("#1c1d22"))
    for i, c in enumerate(("#ff5f57", "#febc2e", "#28c840")):
        p.setBrush(QColor(c))
        p.setPen(Qt.NoPen)
        p.drawEllipse(QRectF(14 + i * 20, 10, 12, 12))
    p.setPen(QColor("#9aa0ad"))
    p.drawText(QRectF(0, 0, W, 32), Qt.AlignCenter, "./install.sh  —  step 6/7: find devices & map fans")
    y = 52
    for segs in lines:
        x = 22
        for text, col, bold in segs:
            f = QFont("DejaVu Sans Mono", 11)
            f.setBold(bold)
            p.setFont(f)
            p.setPen(QColor(col))
            p.drawText(x, y, text)
            x += p.fontMetrics().horizontalAdvance(text)
        y += lh
    p.end()
    img.save(str(out))
    print("saved", out)


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "docs/screenshots")
    out.mkdir(parents=True, exist_ok=True)
    random.seed(7)
    app = QApplication(sys.argv)
    app.setStyleSheet(gui.STYLE)
    shot(app, out / "app-music.png", "music_spectrum", {"rainbow": True, "brightness": 100}, seconds=2.2)
    shot(app, out / "app-interactive.png", "scroll_wheel", {"scroll_step": 15})
    shot(app, out / "app-ambient.png", "aurora", {"speed": 45}, seconds=4)
    shot(app, out / "app-devices.png", "rainbow_ring", {"speed": 40}, tab=1)
    wizard_image(out / "setup-wizard.png")


if __name__ == "__main__":
    main()
