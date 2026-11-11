"""Qt window + tray icon for rgbctl."""
from __future__ import annotations

import json
import math
import re
import signal
import sys

from PySide6.QtCore import QFileSystemWatcher, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QConicalGradient, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QColorDialog, QComboBox, QFormLayout, QFrame, QGridLayout, QGroupBox,
    QHBoxLayout, QInputDialog, QLabel, QListWidget, QListWidgetItem, QMainWindow, QMenu,
    QMessageBox, QPushButton, QSizePolicy, QSlider, QSpinBox, QSystemTrayIcon, QTabWidget,
    QScrollArea, QVBoxLayout, QWidget)

from . import autostart
from .config import (DEFAULT_STATE, STATE_FILE, delete_profile, list_profiles, load_profile, load_state,
                     save_profile, save_state)
from .effects import CATEGORY_ORDER, EFFECTS
from .engine import Engine

STYLE = """
QWidget { background: #15161a; color: #e6e6e6; font-size: 10.5pt; }
QGroupBox { border: 1px solid #2c2e35; border-radius: 8px; margin-top: 14px; padding: 10px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #9aa0ad; }
QListWidget { background: #1c1d22; border: 1px solid #2c2e35; border-radius: 8px; padding: 4px; }
QListWidget::item { padding: 7px 10px; border-radius: 6px; }
QListWidget::item:selected { background: #3b5bdb; color: white; }
QListWidget::item:hover:!selected { background: #26282e; }
QPushButton { background: #26282e; border: 1px solid #343741; border-radius: 6px; padding: 6px 12px; }
QPushButton:hover { background: #30333b; }
QPushButton:pressed { background: #3b5bdb; }
QComboBox, QSpinBox { background: #1c1d22; border: 1px solid #343741; border-radius: 6px; padding: 4px 8px; }
QSlider::groove:horizontal { height: 6px; background: #2c2e35; border-radius: 3px; }
QSlider::sub-page:horizontal { background: #3b5bdb; border-radius: 3px; }
QSlider::handle:horizontal { width: 16px; margin: -6px 0; border-radius: 8px; background: #e6e6e6; }
QTabWidget::pane { border: none; }
QTabBar::tab { background: #1c1d22; padding: 8px 18px; border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px; }
QTabBar::tab:selected { background: #26282e; color: white; }
QLabel#help { color: #9aa0ad; }
QLabel#status { color: #9aa0ad; padding: 2px 6px; }
"""

SWATCHES = ["#ff0000", "#ff6a00", "#ffd000", "#00ff40", "#00e5ff", "#0050ff",
            "#8000ff", "#ff00c8", "#ffffff"]


def make_icon() -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    g = QConicalGradient(32, 32, 90)
    for i, c in enumerate(["#ff0000", "#ffff00", "#00ff00", "#00ffff", "#0000ff", "#ff00ff", "#ff0000"]):
        g.setColorAt(i / 6, QColor(c))
    p.setPen(QPen(g, 9))
    p.drawEllipse(QRectF(9, 9, 46, 46))
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#e6e6e6"))
    p.drawEllipse(QRectF(25, 25, 14, 14))
    p.end()
    return QIcon(pm)


class Preview(QWidget):
    """Draws every fan/fixture as a ring of its LEDs, live."""

    def __init__(self, engine: Engine):
        super().__init__()
        self.engine = engine
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#1c1d22"))
        lay, colors = self.engine.layout, self.engine.preview
        if not lay or not colors or len(colors) != len(lay.leds):
            p.setPen(QColor("#9aa0ad"))
            p.drawText(self.rect(), Qt.AlignCenter, self.engine.status)
            return
        groups: dict[int, list] = {}
        for led, c in zip(lay.leds, colors):
            groups.setdefault(led.unit, []).append((led.local, c))
        n = lay.units
        cols = min(n, 7)
        rows = math.ceil(n / cols)
        cw = self.width() / cols
        ch = (self.height() - 8) / rows
        r = min(cw, ch - 16) * 0.36
        font = p.font()
        font.setPointSizeF(7.5)
        p.setFont(font)
        for u in range(n):
            cx = cw * (u % cols + 0.5)
            cy = ch * (u // cols) + ch / 2 - 6
            leds = groups.get(u, [])
            # Fan body
            avg = [sum(c[i] for _, c in leds) / max(1, len(leds)) for i in range(3)]
            glow = QColor.fromRgbF(*(min(1, v) for v in avg), 0.25)
            p.setPen(Qt.NoPen)
            p.setBrush(glow)
            p.drawEllipse(QPointF(cx, cy), r * 1.15, r * 1.15)
            p.setBrush(QColor("#101114"))
            p.drawEllipse(QPointF(cx, cy), r * 0.62, r * 0.62)
            # LEDs around the ring (cap at 24 dots so dense devices stay readable)
            step = max(1, len(leds) // 24)
            shown = leds[::step]
            for i, (_local, c) in enumerate(shown):
                a = 2 * math.pi * i / max(1, len(shown)) - math.pi / 2
                q = QColor.fromRgbF(*(min(1, max(0, v)) for v in c))
                p.setBrush(q)
                p.drawEllipse(QPointF(cx + math.cos(a) * r * 0.85, cy + math.sin(a) * r * 0.85),
                              max(2.5, r * 0.16), max(2.5, r * 0.16))
            p.setPen(QColor("#9aa0ad"))
            name = lay.unit_names[u] if u < len(lay.unit_names) else ""
            name = re.sub(r"ARGB_V2_(\d+)", r"Header \1", name)
            name = p.fontMetrics().elidedText(name, Qt.ElideRight, int(cw - 6))
            p.drawText(QRectF(cx - cw / 2 + 3, cy + r * 1.15, cw - 6, 16), Qt.AlignCenter, name)


class ColorButton(QPushButton):
    def __init__(self, on_change):
        super().__init__()
        self.on_change = on_change
        self.color = "#ffffff"
        self.setFixedSize(64, 30)
        self.clicked.connect(self.pick)

    def set(self, hexcol: str):
        self.color = hexcol
        self.setStyleSheet(f"background: {hexcol}; border: 2px solid #343741; border-radius: 6px;")

    def pick(self):
        c = QColorDialog.getColor(QColor(self.color), self, "Pick color")
        if c.isValid():
            self.set(c.name())
            self.on_change(c.name())


MODE_LABELS = {
    "Interactive": "🖱   Interactive",
    "Music": "🎵   Music",
    "Ambient": "🌌   Ambient",
    "Fan rings": "🌀   Fan Rings",
    "Classic": "🎨   Classic",
    "System": "📈   System",
    "Tools": "🔧   Tools",
}


class AudioMeter(QWidget):
    """Live view of what the music analyser hears: 16-band spectrum, bass/mid/treble, beat light."""

    def __init__(self, engine: Engine):
        super().__init__()
        self.engine = engine
        self.setMinimumHeight(86)
        self.timer = QTimer(self, interval=40)
        self.timer.timeout.connect(self.update)
        self.timer.start()

    def paintEvent(self, _):
        import time as _t
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#101114"))
        a = self.engine.audio
        w, h = self.width(), self.height()
        if not (self.engine.effect_key or "").startswith("music"):
            p.setPen(QColor("#7c8396"))
            p.drawText(self.rect(), Qt.AlignCenter, "Pick a music style to start listening")
            return
        # Spectrum
        sw = w * 0.62
        n = len(a.bands)
        bw = sw / n
        for i, v in enumerate(a.bands):
            bh = max(2, v * (h - 18))
            p.fillRect(QRectF(6 + i * bw, h - 14 - bh, bw - 3, bh), QColor.fromHsvF(0.78 * i / n * 0.999, 0.85, 1))
        p.setPen(QColor("#7c8396"))
        f = p.font()
        f.setPointSizeF(7.5)
        p.setFont(f)
        p.drawText(QRectF(6, h - 13, sw, 12), Qt.AlignLeft, "bass")
        p.drawText(QRectF(6, h - 13, sw - 6, 12), Qt.AlignRight, "treble")
        # Bass / mid / treble bars
        x0 = sw + 18
        for j, (name, v, col) in enumerate((("B", a.bass, "#ff3b3b"), ("M", a.mid, "#ffd23b"),
                                            ("T", a.treble, "#3bb8ff"))):
            x = x0 + j * 26
            bh = max(2, v * (h - 18))
            p.fillRect(QRectF(x, h - 14 - bh, 18, bh), QColor(col))
            p.setPen(QColor("#9aa0ad"))
            p.drawText(QRectF(x, h - 13, 18, 12), Qt.AlignCenter, name)
        # Beat light
        age = _t.monotonic() - a.beat_at
        k = max(0.0, 1 - age / 0.25)
        cx = w - 30
        p.setPen(Qt.NoPen)
        p.setBrush(QColor.fromRgbF(1, 1, 1, 0.12 + 0.88 * k))
        p.drawEllipse(QPointF(cx, h / 2 - 8), 13, 13)
        p.setPen(QColor("#9aa0ad"))
        p.drawText(QRectF(cx - 30, h / 2 + 8, 60, 14), Qt.AlignCenter, f"beat {a.beats}")


class MainWindow(QMainWindow):
    def __init__(self, engine: Engine, state: dict):
        super().__init__()
        self.engine = engine
        self.state = state
        self.quitting = False
        self._loading = False
        self.setWindowTitle("RGB Control")
        self.setWindowIcon(make_icon())
        self.resize(980, 640)

        self.save_timer = QTimer(self, singleShot=True, interval=400)
        self.save_timer.timeout.connect(lambda: save_state(self.state))

        tabs = QTabWidget()
        tabs.addTab(self._lighting_tab(), "Lighting")
        self.devices_tab = QWidget()
        self.devices_layout = QVBoxLayout(self.devices_tab)
        self.devices_layout.addWidget(QLabel("Waiting for devices…"))
        dev_scroll = QScrollArea()
        dev_scroll.setWidgetResizable(True)
        dev_scroll.setFrameShape(QFrame.NoFrame)
        dev_scroll.setWidget(self.devices_tab)
        tabs.addTab(dev_scroll, "Devices && Settings")
        self.devices_built = False

        self.status = QLabel(objectName="status")
        root = QWidget()
        v = QVBoxLayout(root)
        v.addWidget(tabs)
        v.addWidget(self.status)
        self.setCentralWidget(root)

        self.tick = QTimer(self, interval=40)
        self.tick.timeout.connect(self._on_tick)
        self.tick.start()

        self.watcher = QFileSystemWatcher([str(STATE_FILE)] if STATE_FILE.exists() else [])
        self.watcher.fileChanged.connect(self._external_change)

        self._setup_tray()
        self._load_into_controls()

    # ---- UI construction --------------------------------------------------------
    def _lighting_tab(self) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)

        self.mode_list = QListWidget()
        self.mode_list.setFixedWidth(190)
        for cat in CATEGORY_ORDER:
            n = sum(1 for c in EFFECTS.values() if c.category == cat)
            it = QListWidgetItem(f"{MODE_LABELS.get(cat, cat)}")
            it.setToolTip(f"{n} styles")
            it.setData(Qt.UserRole, cat)
            self.mode_list.addItem(it)
        self.mode_list.currentRowChanged.connect(self._mode_chosen)
        h.addWidget(self.mode_list)

        right = QVBoxLayout()
        self.preview = Preview(self.engine)
        pv = QGroupBox("Live preview")
        pvl = QVBoxLayout(pv)
        self.info = QLabel(objectName="info")
        self.info.setStyleSheet("color: #c9d1e0; font-size: 11pt; padding: 2px 4px;")
        self.info.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        pvl.addWidget(self.preview, 1)
        pvl.addWidget(self.info, 0)
        right.addWidget(pv, 3)

        lower = QHBoxLayout()
        ctl = QGroupBox("Style && settings")
        form = QFormLayout(ctl)
        self.style = QComboBox()
        self.style.currentIndexChanged.connect(self._style_chosen)
        form.addRow("Style", self.style)
        self.help = QLabel(objectName="help", wordWrap=True)
        self.help.setMinimumHeight(70)
        self.help.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        form.addRow(self.help)

        self.c1 = ColorButton(lambda c: self._set_param("color1", c))
        self.c2 = ColorButton(lambda c: self._set_param("color2", c))
        sw = QHBoxLayout()
        sw.setContentsMargins(0, 0, 0, 0)
        sw.addWidget(self.c1)
        for hexcol in SWATCHES:
            b = QPushButton()
            b.setFixedSize(22, 22)
            b.setStyleSheet(f"background:{hexcol}; border-radius:11px; border:1px solid #343741;")
            b.clicked.connect(lambda _=False, c=hexcol: (self.c1.set(c), self._set_param("color1", c)))
            sw.addWidget(b)
        sw.addStretch()
        self.row_c1 = QWidget()
        self.row_c1.setLayout(sw)
        self.lbl_c1 = QLabel("Color 1")
        form.addRow(self.lbl_c1, self.row_c1)
        self.lbl_c2 = QLabel("Color 2")
        form.addRow(self.lbl_c2, self.c2)

        self.param_rows = {}     # key -> (label, row widget)
        self.param_sliders = {}  # key -> (slider, default, fmt, value label)
        self._slider_row(form, "Speed", "speed", 0, 100, 40, lambda v: f"{v}%")
        self._slider_row(form, "Fireflies", "firefly_count", 1, 12, 3, lambda v: f"{v}")
        self._slider_row(form, "Color per notch", "scroll_step", 3, 60, 15, lambda v: f"{v}°")

        opts = QHBoxLayout()
        opts.setContentsMargins(0, 0, 0, 0)
        self.rainbow = QCheckBox("Rainbow colors")
        self.rainbow.toggled.connect(lambda v: self._set_param("rainbow", v))
        self.reverse = QCheckBox("Reverse direction")
        self.reverse.toggled.connect(lambda v: self._set_param("reverse", v))
        opts.addWidget(self.rainbow)
        opts.addWidget(self.reverse)
        opts.addStretch()
        self.row_opts = QWidget()
        self.row_opts.setLayout(opts)
        form.addRow(self.row_opts)

        self.temp_src = QComboBox()
        self.temp_src.addItem("CPU temperature", "cpu")
        self.temp_src.addItem("GPU temperature", "gpu")
        self.temp_src.addItem("Hottest of both", "max")
        self.temp_src.currentIndexChanged.connect(
            lambda _: self._set_param("temp_source", self.temp_src.currentData()))
        self.lbl_temp = QLabel("Source")
        form.addRow(self.lbl_temp, self.temp_src)
        self._slider_row(form, "Brightness", "brightness", 0, 100, 100, lambda v: f"{v}%")
        lower.addWidget(ctl, 1)

        # Music: one tuning panel shared by every music style.
        self.tune = QGroupBox("Music tuning  (applies to every music style)")
        tv = QVBoxLayout(self.tune)
        self.meter = AudioMeter(self.engine)
        self.meter.setFixedHeight(92)
        tv.addWidget(self.meter)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        tf = QFormLayout(inner)
        tf.setContentsMargins(0, 6, 6, 0)
        scroll.setWidget(inner)
        tv.addWidget(scroll, 1)
        x = lambda v: f"×{2 ** ((v - 50) / 25):.2f}"  # noqa: E731
        self._slider_row(tf, "Overall sensitivity", "sensitivity", 0, 100, 50,
                         lambda v: f"×{0.4 + v / 100 * 1.6:.2f}")
        self._slider_row(tf, "Bass boost", "bass_gain", 0, 100, 50, x)
        self._slider_row(tf, "Mid boost", "mid_gain", 0, 100, 50, x)
        self._slider_row(tf, "Treble boost", "treble_gain", 0, 100, 50, x)
        self._slider_row(tf, "Bass ends at", "bass_cutoff", 60, 300, 160, lambda v: f"{v} Hz")
        self._slider_row(tf, "Beat threshold", "beat_threshold", 0, 100, 30,
                         lambda v: f"{1.15 + v / 100:.2f}× avg")
        self._slider_row(tf, "Min gap between beats", "beat_gap", 100, 800, 220, lambda v: f"{v} ms")
        self._slider_row(tf, "Smoothing", "smoothing", 0, 100, 50, lambda v: f"{v}%")
        self._slider_row(tf, "Noise gate", "noise_gate", 0, 100, 10, lambda v: f"{v}%")
        self._slider_row(tf, "Min brightness", "music_floor", 0, 50, 4, lambda v: f"{v}%")
        tip = QLabel("Beat threshold: lower = more beats detected. Bass boost: make kicks hit harder. "
                     "Noise gate: ignore quiet hiss. Smoothing: higher = calmer, slower fades.",
                     objectName="help", wordWrap=True)
        tf.addRow(tip)
        reset = QPushButton("Reset music tuning")
        reset.clicked.connect(self._reset_music)
        tf.addRow(reset)
        lower.addWidget(self.tune, 1)
        right.addLayout(lower, 5)

        prof = QGroupBox("Profiles")
        ph = QHBoxLayout(prof)
        self.profiles = QComboBox()
        self.profiles.setMinimumWidth(200)
        ph.addWidget(self.profiles, 1)
        for text, fn in (("Load", self._load_profile), ("Save as…", self._save_profile),
                         ("Delete", self._delete_profile)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            ph.addWidget(b)
        right.addWidget(prof)
        self._refresh_profiles()

        h.addLayout(right, 1)
        return w

    def _build_devices_tab(self):
        while self.devices_layout.count():
            item = self.devices_layout.takeAt(0)
            old = item.widget()
            if old:
                old.setParent(None)
                old.deleteLater()
        st = self.state
        intro = QLabel("Fan headers are the connectors your ARGB fans plug into. Tick the ones in use, say how "
                       "many fans are chained on each, and press Identify to blink a header white so you can "
                       "see what's on it.", objectName="help", wordWrap=True)
        self.devices_layout.addWidget(intro)
        for name, zones, kind in self.engine.device_names():
            box = QGroupBox(f"{kind}: {name}")
            g = QGridLayout(box)
            dev_cb = QCheckBox("Control this device")
            dev_cb.setChecked(st["devices"].get(name, True))
            dev_cb.toggled.connect(lambda v, n=name: self._set_device(n, v))
            g.addWidget(dev_cb, 0, 0, 1, 4)
            headers = [z for z, hdr in zones if hdr]
            others = [z for z, hdr in zones if not hdr]
            r = 1
            for z in headers:
                key = f"{name}::{z}"
                cfg = st["zones"].get(key, {})
                cb = QCheckBox(f"{z}" + (f"  —  {cfg['label']}" if cfg.get("label") else "") + "   (fan header)")
                cb.setChecked(bool(cfg.get("enabled", False)))
                cb.toggled.connect(lambda v, k=key: self._set_zone(k, "enabled", v))
                g.addWidget(cb, r, 0)
                g.addWidget(QLabel("Fans:"), r, 1)
                sp = QSpinBox(minimum=1, maximum=12, value=int(cfg.get("fans", 1)))
                sp.setFixedWidth(70)
                sp.valueChanged.connect(lambda v, k=key: self._set_zone(k, "fans", v))
                g.addWidget(sp, r, 2)
                ident = QPushButton("Identify")
                ident.clicked.connect(lambda _=False, n=name, zz=z: self.engine.identify(n, zz))
                g.addWidget(ident, r, 3)
                r += 1
            for z in others:
                key = f"{name}::{z}"
                cfg = st["zones"].get(key, {})
                cb = QCheckBox(z + (f"  —  {cfg['label']}" if cfg.get("label") else ""))
                cb.setChecked(bool(cfg.get("enabled", True)))
                cb.toggled.connect(lambda v, k=key: self._set_zone(k, "enabled", v))
                g.addWidget(cb, r, 0)
                if len(others) > 1:
                    ident = QPushButton("Identify")
                    ident.clicked.connect(lambda _=False, n=name, zz=z: self.engine.identify(n, zz))
                    g.addWidget(ident, r, 3)
                r += 1
            g.setColumnStretch(0, 1)
            self.devices_layout.addWidget(box)

        gen = QGroupBox("General")
        f = QFormLayout(gen)
        lpf = QSpinBox(minimum=1, maximum=60, value=int(st.get("leds_per_fan", 8)))
        lpf.setFixedWidth(80)
        lpf.valueChanged.connect(lambda v: self._set_top("leds_per_fan", v))
        test = QPushButton("Run Fan Map Test")
        test.clicked.connect(lambda: self._select_effect("fan_test"))
        row = QHBoxLayout()
        row.addWidget(lpf)
        row.addWidget(test)
        row.addStretch()
        rw = QWidget()
        rw.setLayout(row)
        f.addRow("LEDs per fan", rw)
        f.addRow(QLabel("Use the Fan Map Test: each case fan should be fully lit in one color. "
                        "Two colors on one fan → lower it. Part of the last fan dark → raise it.",
                        objectName="help", wordWrap=True))
        fps = QSpinBox(minimum=5, maximum=60, value=int(st.get("fps", 30)))
        fps.setFixedWidth(80)
        fps.valueChanged.connect(lambda v: self._set_top("fps", v))
        f.addRow("Animation FPS", fps)
        auto = QCheckBox("Start RGB Control when I log in (in the tray)")
        auto.setChecked(autostart.is_enabled())
        auto.toggled.connect(autostart.set_enabled)
        f.addRow(auto)
        self.devices_layout.addWidget(gen)
        self.devices_layout.addStretch()
        self.devices_built = True

    def _setup_tray(self):
        self.tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(make_icon(), self)
        self.tray.setToolTip("RGB Control")
        m = QMenu()
        m.addAction("Show window", self.show_window)
        em = m.addMenu("Effect")
        subs = {}
        for key, cls in EFFECTS.items():
            if cls.category == "Tools":
                continue
            if cls.category not in subs:
                subs[cls.category] = em.addMenu(cls.category)
            subs[cls.category].addAction(cls.label, lambda k=key: self._select_effect(k))
        prof_menu = m.addMenu("Profiles")
        prof_menu.aboutToShow.connect(lambda: self._fill_profile_menu(prof_menu))
        m.addAction("Lights off", lambda: self._select_effect("off"))
        m.addSeparator()
        m.addAction("Quit", self.quit_app)
        self.tray.setContextMenu(m)
        self.tray.activated.connect(
            lambda r: self.show_window() if r == QSystemTrayIcon.Trigger else None)
        self.tray.show()

    def _fill_profile_menu(self, menu):
        menu.clear()
        names = list_profiles()
        if not names:
            menu.addAction("(no profiles saved)").setEnabled(False)
        for n in names:
            menu.addAction(n, lambda n=n: self._apply_profile(n))

    # ---- state handling ----------------------------------------------------------
    def _commit(self):
        self.engine.update_state(self.state)
        self.save_timer.start()

    def _set_param(self, k, v):
        if self._loading:
            return
        self.state["params"][k] = v
        self._commit()

    def _set_top(self, k, v):
        self.state[k] = v
        self._commit()

    def _set_zone(self, key, k, v):
        self.state["zones"].setdefault(key, {})[k] = v
        self._commit()

    def _set_device(self, name, v):
        self.state["devices"][name] = v
        self._commit()

    # ---- modes & styles ------------------------------------------------------------
    def _slider_row(self, form, label, key, lo, hi, default, fmt):
        s = QSlider(Qt.Horizontal, minimum=lo, maximum=hi)
        val = QLabel(fmt(default))
        val.setFixedWidth(78)
        val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        def changed(v):
            val.setText(fmt(v))
            self._set_param(key, v)
        s.valueChanged.connect(changed)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(s, 1)
        row.addWidget(val)
        w = QWidget()
        w.setLayout(row)
        lbl = QLabel(label)
        form.addRow(lbl, w)
        self.param_rows[key] = (lbl, w)
        self.param_sliders[key] = (s, default, fmt, val)

    def _styles_of(self, cat):
        return [k for k, c in EFFECTS.items() if c.category == cat]

    def _mode_chosen(self, row):
        if row < 0:
            return
        cat = self.mode_list.item(row).data(Qt.UserRole)
        keys = self._styles_of(cat)
        want = getattr(self, "_want", None)
        self._want = None
        if not (want in keys):
            want = self.state.get("last_style", {}).get(cat)
        if want not in keys:
            want = keys[0]
        self.style.blockSignals(True)
        self.style.clear()
        for k in keys:
            self.style.addItem(EFFECTS[k].label, k)
        self.style.setCurrentIndex(keys.index(want))
        self.style.blockSignals(False)
        self._style_chosen(self.style.currentIndex())

    def _style_chosen(self, idx):
        if idx < 0:
            return
        key = self.style.itemData(idx)
        if not self._loading:
            self.state["effect"] = key
            self.state.setdefault("last_style", {})[EFFECTS[key].category] = key
            self._commit()
        self._show_controls(key)

    def _select_effect(self, key):
        if key not in EFFECTS:
            return
        cat = EFFECTS[key].category
        row = CATEGORY_ORDER.index(cat)
        self._want = key
        if self.mode_list.currentRow() != row:
            self.mode_list.setCurrentRow(row)
        else:
            self._mode_chosen(row)

    def _show_controls(self, key):
        cls = EFFECTS[key]
        u = cls.uses
        self.help.setText(cls.help)
        for widgets, need in (((self.lbl_c1, self.row_c1), "color1"), ((self.lbl_c2, self.c2), "color2"),
                              ((self.lbl_temp, self.temp_src), "temp_source")):
            for wdg in widgets:
                wdg.setVisible(need in u)
        for k in ("speed", "firefly_count", "scroll_step"):
            for wdg in self.param_rows[k]:
                wdg.setVisible(k in u)
        self.rainbow.setVisible("rainbow" in u)
        self.reverse.setVisible("reverse" in u)
        self.row_opts.setVisible("rainbow" in u or "reverse" in u)
        self.tune.setVisible(cls.category == "Music")

    def _reset_music(self):
        for k in ("sensitivity", "bass_gain", "mid_gain", "treble_gain", "bass_cutoff", "beat_threshold",
                  "beat_gap", "smoothing", "noise_gate", "music_floor"):
            self.state["params"][k] = DEFAULT_STATE["params"][k]
        self._commit()
        self._load_into_controls()

    def _load_into_controls(self):
        self._loading = True
        p = self.state["params"]
        self.c1.set(p["color1"])
        self.c2.set(p["color2"])
        for key, (s, default, fmt, val) in self.param_sliders.items():
            v = int(p.get(key, default))
            s.setValue(v)
            val.setText(fmt(v))
        self.rainbow.setChecked(bool(p.get("rainbow")))
        self.reverse.setChecked(bool(p.get("reverse")))
        self.temp_src.setCurrentIndex(max(0, self.temp_src.findData(p.get("temp_source", "cpu"))))
        self._select_effect(self.state["effect"])
        self._show_controls(self.state["effect"])
        self._loading = False

    def _external_change(self, path):
        # Another rgbctl command (CLI) edited the state file.
        if path not in self.watcher.files() and STATE_FILE.exists():
            self.watcher.addPath(str(STATE_FILE))
        new = load_state()
        if json.dumps(new, sort_keys=True) != json.dumps(self.state, sort_keys=True):
            self.state = new
            self.engine.update_state(self.state)
            self._load_into_controls()

    # ---- profiles ----------------------------------------------------------------
    def _refresh_profiles(self):
        self.profiles.clear()
        self.profiles.addItems(list_profiles())

    def _apply_profile(self, name):
        try:
            self.state = load_profile(name, self.state)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "Profile", f"Could not load {name}: {e}")
            return
        self._commit()
        self._load_into_controls()

    def _load_profile(self):
        if self.profiles.currentText():
            self._apply_profile(self.profiles.currentText())

    def _save_profile(self):
        name, ok = QInputDialog.getText(self, "Save profile", "Profile name:",
                                        text=self.profiles.currentText())
        name = name.strip().replace("/", "-")
        if ok and name:
            save_profile(name, self.state)
            self._refresh_profiles()
            self.profiles.setCurrentText(name)

    def _delete_profile(self):
        name = self.profiles.currentText()
        if name and QMessageBox.question(self, "Delete profile", f"Delete '{name}'?") == QMessageBox.Yes:
            delete_profile(name)
            self._refresh_profiles()

    # ---- misc -----------------------------------------------------------------------
    def _on_tick(self):
        self.preview.update()
        self.status.setText(self.engine.status)
        eff = self.engine.effect
        text = ""
        if eff is not None:
            if self.engine.effect_key and self.engine.effect_key.startswith("music"):
                # The Music tuning panel has the full meter; only report problems here.
                if not self.engine.audio.available:
                    text = "⚠ parec not found: install pulseaudio-utils so music styles can hear audio"
            elif eff.needs_input and self.engine.inp.error:
                text = f"⚠ {self.engine.inp.error}"
            else:
                text = eff.info
        self.info.setText(text)
        self.info.setVisible(bool(text))
        if not self.devices_built and self.engine.layout is not None:
            self._build_devices_tab()

    def show_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, ev):
        if self.tray and not self.quitting:
            ev.ignore()
            self.hide()
            self.tray.showMessage("RGB Control", "Still running in the tray. Right-click the icon to quit.",
                                  QSystemTrayIcon.Information, 2500)
        else:
            ev.accept()

    def quit_app(self):
        self.quitting = True
        save_state(self.state)
        QApplication.quit()


def run(start_hidden: bool = False) -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("RGB Control")
    app.setDesktopFileName("rgbctl")
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(STYLE)

    state = load_state()
    if not STATE_FILE.exists():
        save_state(state)
    engine = Engine(state)
    engine.start()
    win = MainWindow(engine, state)

    # A second launch sends SIGUSR1 to bring this window up; SIGTERM/SIGINT quit cleanly.
    # (The window's 40 ms timer lets Python run these handlers inside Qt's loop.)
    signal.signal(signal.SIGUSR1, lambda *_: QTimer.singleShot(0, win.show_window))
    signal.signal(signal.SIGTERM, lambda *_: QTimer.singleShot(0, win.quit_app))
    signal.signal(signal.SIGINT, lambda *_: QTimer.singleShot(0, win.quit_app))

    if not (start_hidden and win.tray):
        win.show()
    rc = app.exec()
    engine.stop()
    engine.join(2)
    engine.backend.close()
    return rc
