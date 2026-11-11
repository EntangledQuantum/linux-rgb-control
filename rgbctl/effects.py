"""Lighting effects. Each one paints every LED from the same clock, so all
devices stay in sync. Colors are (r, g, b) floats in 0..1."""
from __future__ import annotations

import colorsys
import math
import random
from dataclasses import dataclass

BLACK = (0.0, 0.0, 0.0)


def hex_to_rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def hsv(h: float, s: float = 1.0, v: float = 1.0):
    return colorsys.hsv_to_rgb(h % 1.0, s, v)


def lerp(a, b, t: float):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t)


def scale(c, k: float):
    return (c[0] * k, c[1] * k, c[2] * k)


def tri(v: float) -> float:
    """0→1→0 triangle wave with period 1."""
    return 1.0 - abs(2.0 * (v % 1.0) - 1.0)


def speed_to_rate(speed: float) -> float:
    """Slider 0..100 → cycles per second."""
    s = max(0.0, min(100.0, speed)) / 100.0
    return 0.02 + s * s * 1.6


@dataclass
class Ctx:
    phase: float      # cycles elapsed, advances with the speed slider
    t: float          # seconds elapsed
    dt: float         # seconds since last frame
    c1: tuple
    c2: tuple
    p: dict           # raw params
    units: int
    temps: object
    audio: object
    lpf: int = 8      # LEDs per case fan
    inp: object = None  # InputEvents


class Effect:
    key = ""
    label = ""
    uses: tuple = ("color1", "speed")
    help = ""
    category = "Classic"
    needs_input = False   # reads mouse/keyboard activity
    info = ""             # live status line shown under the preview

    def reset(self, n: int) -> None:
        pass

    def render(self, ctx: Ctx, leds) -> list:
        raise NotImplementedError


class Static(Effect):
    key, label, uses = "static", "Static", ("color1",)
    help = "One solid color on every fan."

    def render(self, ctx, leds):
        return [ctx.c1] * len(leds)


class Breathing(Effect):
    key, label, uses = "breathing", "Breathing", ("color1", "speed", "rainbow")
    help = "Fades in and out together. 'Rainbow' changes color each breath."

    def render(self, ctx, leds):
        b = ((1 - math.cos(2 * math.pi * ctx.phase)) / 2) ** 1.6
        c = hsv(math.floor(ctx.phase) * 0.17) if ctx.p.get("rainbow") else ctx.c1
        return [scale(c, b)] * len(leds)


class ColorCycle(Effect):
    key, label, uses = "color_cycle", "Color Cycle", ("speed",)
    help = "All fans shift through the spectrum together."

    def render(self, ctx, leds):
        return [hsv(ctx.phase * 0.25)] * len(leds)


class RainbowWave(Effect):
    key, label, uses = "rainbow_wave", "Rainbow Wave", ("speed", "reverse")
    help = "A rainbow that flows across all fans."

    def render(self, ctx, leds):
        ph = ctx.phase * 0.5
        return [hsv(l.pos - ph) for l in leds]


class Gradient(Effect):
    key, label, uses = "gradient", "Gradient", ("color1", "color2", "speed", "reverse")
    help = "Blend from Color 1 to Color 2 across the rig, slowly drifting."

    def render(self, ctx, leds):
        ph = ctx.phase * 0.25
        return [lerp(ctx.c1, ctx.c2, tri(l.pos * 0.5 + ph)) for l in leds]


class Strobe(Effect):
    key, label, uses = "strobe", "Strobe", ("color1", "speed", "rainbow")
    help = "Sharp flashes."

    def render(self, ctx, leds):
        ph = ctx.phase * 3
        on = (ph % 1.0) < 0.18
        c = hsv(math.floor(ph) * 0.13) if ctx.p.get("rainbow") else ctx.c1
        return [c if on else BLACK] * len(leds)


class Comet(Effect):
    key, label, uses = "comet", "Comet", ("color1", "color2", "speed", "rainbow", "reverse")
    help = "A bright head with a fading tail runs from fan to fan over a Color 2 background."

    def render(self, ctx, leds):
        head = ctx.phase * 0.5 % 1.0
        bg = scale(ctx.c2, 0.06)
        out = []
        for l in leds:
            d = (head - l.pos) % 1.0
            k = math.exp(-d * 9.0)
            c = hsv(head + 0.3 * d) if ctx.p.get("rainbow") else ctx.c1
            out.append(lerp(bg, c, k))
        return out


class Spin(Effect):
    key, label, uses = "spin", "Spin", ("color1", "color2", "speed", "rainbow", "reverse")
    help = "A light spins around each fan ring. Needs the right 'LEDs per fan' setting."

    def render(self, ctx, leds):
        head = ctx.phase % 1.0
        bg = scale(ctx.c2, 0.08)
        out = []
        for l in leds:
            d = (head - l.local) % 1.0
            k = math.exp(-d * 6.0)
            c = hsv(l.unit / max(1, ctx.units) + ctx.phase * 0.05) if ctx.p.get("rainbow") else ctx.c1
            out.append(lerp(bg, c, k))
        return out


class Fire(Effect):
    key, label, uses = "fire", "Fire", ("speed",)
    help = "Flickering flames, each fan burning on its own."

    PALETTE = [(0, 0, 0), (0.5, 0.0, 0.0), (1.0, 0.15, 0.0), (1.0, 0.45, 0.0), (1.0, 0.8, 0.2)]

    def reset(self, n):
        self.heat = {}

    def _pal(self, h):
        h = max(0.0, min(0.999, h)) * (len(self.PALETTE) - 1)
        i = int(h)
        return lerp(self.PALETTE[i], self.PALETTE[i + 1], h - i)

    def render(self, ctx, leds):
        t = ctx.t * (0.6 + ctx.p.get("speed", 50) / 40.0)
        out = []
        for l in leds:
            s = l.unit * 7.13 + l.rnd * 3.0
            h = 0.55 + 0.18 * math.sin(t * 3.1 + s) + 0.12 * math.sin(t * 7.7 + s * 2.3) \
                + 0.08 * math.sin(t * 13.3 + s * 5.1) + random.uniform(-0.06, 0.06)
            out.append(self._pal(h))
        return out


class Twinkle(Effect):
    key, label, uses = "twinkle", "Starlight", ("color1", "color2", "speed", "rainbow")
    help = "Random sparkles of Color 1 over a dim Color 2 glow."

    def reset(self, n):
        self.b = [0.0] * n
        self.hue = [0.0] * n

    def render(self, ctx, leds):
        n = len(leds)
        if len(self.b) != n:
            self.reset(n)
        decay = math.exp(-ctx.dt * 3.0)
        chance = ctx.dt * (0.15 + speed_to_rate(ctx.p.get("speed", 50)) * 1.5)
        bg = scale(ctx.c2, 0.12)
        out = []
        for i in range(n):
            self.b[i] *= decay
            if random.random() < chance:
                self.b[i] = 1.0
                self.hue[i] = random.random()
            c = hsv(self.hue[i]) if ctx.p.get("rainbow") else ctx.c1
            out.append(lerp(bg, c, self.b[i]))
        return out


class Police(Effect):
    key, label, uses = "police", "Police", ("speed",)
    help = "Red and blue double flashes, alternating between fans."

    def render(self, ctx, leds):
        ph = ctx.phase * 1.5 % 1.0
        side = 0 if ph < 0.5 else 1
        local = (ph % 0.5) * 2
        on = local < 0.15 or 0.25 < local < 0.4
        out = []
        for l in leds:
            mine = l.unit % 2 == side
            c = (1, 0, 0) if side == 0 else (0, 0.2, 1)
            out.append(c if (on and mine) else BLACK)
        return out


class Temperature(Effect):
    key, label, uses = "temperature", "Temperature", ("temp_source",)
    help = "Blue when cool, through green and yellow, to red when hot (35°C → 85°C)."

    def render(self, ctx, leds):
        ctx.temps.poll()
        src = ctx.p.get("temp_source", "cpu")
        temp = {"cpu": ctx.temps.cpu, "gpu": ctx.temps.gpu}.get(src, max(ctx.temps.cpu, ctx.temps.gpu))
        x = max(0.0, min(1.0, (temp - 35.0) / 50.0))
        c = hsv(0.66 * (1 - x))
        b = 0.85 + 0.15 * math.sin(ctx.t * (1.5 + 4 * x))
        return [scale(c, b)] * len(leds)


class RainbowRing(Effect):
    key, label, uses = "rainbow_ring", "Rainbow Ring", ("speed", "reverse")
    help = "Every fan ring shows a full rainbow that rotates, LED by LED."

    def render(self, ctx, leds):
        return [hsv(l.local + ctx.phase * 0.5 + l.unit * 0.08) for l in leds]


class Marquee(Effect):
    key, label, uses = "marquee", "Marquee", ("color1", "color2", "speed", "rainbow", "reverse")
    help = "Theatre-style chasing lights: every third LED lit, marching around each fan."

    def render(self, ctx, leds):
        step = math.floor(ctx.phase * 4)
        bg = scale(ctx.c2, 0.15)
        out = []
        for l in leds:
            i = round(l.local * ctx.lpf)
            on = (i + step) % 3 == 0
            c = hsv(l.unit * 0.1 + ctx.phase * 0.05) if ctx.p.get("rainbow") else ctx.c1
            out.append(c if on else bg)
        return out


# ---- music ---------------------------------------------------------------------------
MUSIC_USES = ("sensitivity",)


class MusicPulse(Effect):
    key, label = "music", "Music: Pulse"
    uses = ("color1", "color2", "rainbow") + MUSIC_USES
    help = "Everything pulses with the volume. Bass pushes the color from Color 1 toward Color 2."

    def render(self, ctx, leds):
        a = ctx.audio
        fl = ctx.p.get("music_floor", 4) / 100
        b = fl + (1 - fl) * a.level ** 1.2
        out = []
        for l in leds:
            if ctx.p.get("rainbow"):
                c = hsv(ctx.t * 0.05 + l.pos * 0.5 + a.bass * 0.25)
            else:
                c = lerp(ctx.c1, ctx.c2, a.bass)
            out.append(scale(c, b))
        return out


class MusicBeat(Effect):
    key, label = "music_beat", "Music: Beat Party"
    uses = ("color1", "color2", "rainbow") + MUSIC_USES
    help = ("Every beat flashes the whole rig and changes the colors. Rainbow on: new colors on "
            "every beat, different on each fan. Rainbow off: swaps between Color 1 and Color 2.")

    def reset(self, n):
        self.seen = -1
        self.hue = random.random()
        self.flash = 0.0
        self.flip = False

    def render(self, ctx, leds):
        a = ctx.audio
        if a.beats != self.seen:
            if self.seen != -1:
                self.hue = (self.hue + 0.618) % 1.0
                self.flip = not self.flip
                self.flash = 1.0
            self.seen = a.beats
        self.flash *= math.exp(-ctx.dt * 5.0)
        fl = ctx.p.get("music_floor", 4) / 100
        b = max(self.flash, fl + 0.55 * a.bass)
        out = []
        for l in leds:
            if ctx.p.get("rainbow"):
                c = hsv(self.hue + (l.unit % 4) * 0.25)
            else:
                c = ctx.c2 if (self.flip ^ (l.unit % 2 == 1)) else ctx.c1
            out.append(scale(c, b))
        return out


class MusicSpectrum(Effect):
    key, label = "music_spectrum", "Music: Spectrum"
    uses = ("color1", "color2", "rainbow", "reverse") + MUSIC_USES
    help = ("A graphic equalizer across your fans: bass on one end, treble on the other. Each fan ring "
            "fills up with its band's level. Rainbow on: colored by frequency (red bass → violet treble).")

    def render(self, ctx, leds):
        a = ctx.audio
        bands = a.bands
        nb = len(bands)
        units = max(1, ctx.units)
        rev = ctx.p.get("reverse")
        out = []
        for l in leds:
            u = (units - 1 - l.unit) if rev else l.unit
            lo = int(u * nb / units)
            hi = max(lo + 1, int((u + 1) * nb / units))
            v = max(bands[lo:hi])
            frac = u / max(1, units - 1)
            base = hsv(frac * 0.78) if ctx.p.get("rainbow") else lerp(ctx.c1, ctx.c2, v)
            # Ring fill: LEDs around the fan light up in proportion to the level.
            k = 1.0 if l.local <= v else max(0.04, ctx.p.get("music_floor", 4) / 100)
            out.append(scale(base, k * (0.25 + 0.75 * v)))
        return out


class MusicRipple(Effect):
    key, label = "music_ripple", "Music: Ripple"
    uses = ("color1", "color2", "rainbow", "speed", "reverse") + MUSIC_USES
    help = "Every beat sends a wave of light rolling across all fans, over a glow that follows the treble."

    def reset(self, n):
        self.seen = -1
        self.waves = []     # (start time, hue)
        self.hue = random.random()

    def render(self, ctx, leds):
        a = ctx.audio
        if a.beats != self.seen:
            if self.seen != -1:
                self.hue = (self.hue + 0.618) % 1.0
                self.waves.append((ctx.t, self.hue))
            self.seen = a.beats
        v = 0.4 + speed_to_rate(ctx.p.get("speed", 50)) * 1.5   # rig lengths per second
        self.waves = [w for w in self.waves if (ctx.t - w[0]) * v < 1.4]
        glow = scale(ctx.c2, 0.05 + 0.3 * a.treble)
        rev = ctx.p.get("reverse")
        out = []
        for l in leds:
            pos = 1 - l.pos if rev else l.pos
            c = glow
            for t0, hue in self.waves:
                d = pos - (ctx.t - t0) * v
                k = math.exp(-(d / 0.12) ** 2) * math.exp(-(ctx.t - t0) * 0.8)
                if k > 0.01:
                    wc = hsv(hue) if ctx.p.get("rainbow") else ctx.c1
                    c = (max(c[0], wc[0] * k), max(c[1], wc[1] * k), max(c[2], wc[2] * k))
            out.append(c)
        return out


class FanTest(Effect):
    key, label, uses = "fan_test", "Fan Map Test", ()
    help = ("Each case fan should be fully lit in ONE color: red, green, blue, yellow… "
            "If a fan shows two colors, lower 'LEDs per case fan'. If part of the last fan "
            "on a header is dark, raise it.")

    COLORS = [(1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 0), (1, 0, 1), (0, 1, 1), (1, 1, 1), (1, 0.4, 0)]

    def render(self, ctx, leds):
        return [self.COLORS[l.unit % len(self.COLORS)] for l in leds]


class Off(Effect):
    key, label, uses = "off", "Off", ()
    help = "All lights off."

    def render(self, ctx, leds):
        return [BLACK] * len(leds)


for _cls, _cat in ((Spin, "Fan rings"), (RainbowRing, "Fan rings"), (Marquee, "Fan rings"),
                   (MusicBeat, "Music"), (MusicSpectrum, "Music"), (MusicRipple, "Music"),
                   (MusicPulse, "Music"), (Fire, "Ambient"), (Twinkle, "Ambient"),
                   (Temperature, "System"), (FanTest, "Tools"), (Off, "Tools")):
    _cls.category = _cat

from .effects_fun import FUN_EFFECTS  # noqa: E402  (imports names defined above)

CATEGORY_ORDER = ["Interactive", "Music", "Ambient", "Fan rings", "Classic", "System", "Tools"]
_ALL = (Static, Breathing, ColorCycle, RainbowWave, Gradient, Comet, Strobe, Police,
        Spin, RainbowRing, Marquee, Fire, Twinkle, Temperature,
        MusicBeat, MusicSpectrum, MusicRipple, MusicPulse, *FUN_EFFECTS, FanTest, Off)
EFFECTS: dict[str, type[Effect]] = {
    e.key: e for e in sorted(_ALL, key=lambda e: CATEGORY_ORDER.index(e.category))}
