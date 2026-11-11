"""Creative, interactive, system-reactive and ambient effects.

Interactive effects read the mouse wheel, clicks, keypress *counts* and the pointer
position (never which keys were pressed)."""
from __future__ import annotations

import math
import random
import time

from .effects import BLACK, Effect, hsv, lerp, scale, speed_to_rate

FIREFLY = (0.72, 1.0, 0.12)


def clamp(v, lo=0.0, hi=1.0):
    return lo if v < lo else hi if v > hi else v


def ring_dist(a: float, b: float) -> float:
    d = abs(a - b) % 1.0
    return min(d, 1.0 - d)


def maxc(a, b):
    return (max(a[0], b[0]), max(a[1], b[1]), max(a[2], b[2]))


def addc(a, b):
    return (min(1, a[0] + b[0]), min(1, a[1] + b[1]), min(1, a[2] + b[2]))


def ring_size(led) -> int:
    return led.ring if led.kind == "fan" else min(led.ring, 24)


def blob(led, x: float, width: float = 1.4) -> float:
    """Brightness of a 2–3 LED cluster centred at ring position x (0..1)."""
    if led.ring <= 1:
        return 1.0
    d = ring_dist(led.local, x) * ring_size(led)
    return max(0.0, 1.0 - d / width)


class UnitMap:
    """Groups the layout's LEDs by fan/fixture and builds an LED-by-LED path through
    the whole rig (keyboard keys grouped into columns) for things that travel."""

    def __init__(self, leds):
        self.src = leds
        by: dict[int, list[int]] = {}
        for i, l in enumerate(leds):
            by.setdefault(l.unit, []).append(i)
        self.units = sorted(by)
        self.leds_of = by
        self.pos = {u: sum(leds[i].pos for i in ix) / len(ix) for u, ix in by.items()}
        self.kind = {u: leds[ix[0]].kind for u, ix in by.items()}
        steps = []
        for u in self.units:
            ix = by[u]
            if self.kind[u] == "keyboard":
                cols: dict[int, list[int]] = {}
                for i in ix:
                    cols.setdefault(round(leds[i].local * 21), []).append(i)
                steps += [cols[k] for k in sorted(cols)]
            else:
                steps += [[i] for i in sorted(ix, key=lambda i: leds[i].local)]
        self.steps = steps

    def nearest_unit(self, x: float) -> int:
        return min(self.units, key=lambda u: abs(self.pos[u] - x))


class Fun(Effect):
    category = "Interactive"

    def reset(self, n):
        self.um = None

    def umap(self, leds) -> UnitMap:
        if getattr(self, "um", None) is None or self.um.src is not leds:
            self.um = UnitMap(leds)
            self.on_layout(self.um)
        return self.um

    def on_layout(self, um: UnitMap) -> None:
        pass


# ---- fireflies ------------------------------------------------------------------------
class _Fly:
    def __init__(self, um: UnitMap, hue: float, avoid=None):
        choices = [u for u in um.units if u != avoid] or um.units
        self.unit = random.choice(choices)
        self.x = random.random()
        self.v = random.choice((-1, 1)) * random.uniform(0.25, 0.6)   # laps per second
        self.life = random.uniform(2.5, 6.0)
        self.alpha = 0.0
        self.state = "in"
        self.hue = hue
        self.ph = random.random() * 6.28

    def step(self, um: UnitMap, dt: float, sf: float, jumpy=1.0):
        self.x = (self.x + self.v * dt * sf) % 1.0
        if random.random() < dt * 0.4:
            self.v = -self.v
        if self.state == "in":
            self.alpha = min(1.0, self.alpha + dt * 3)
            if self.alpha >= 1:
                self.state = "fly"
        elif self.state == "fly":
            self.life -= dt * sf * jumpy
            if self.life <= 0:
                self.state = "out"
        else:
            self.alpha -= dt * 3
            if self.alpha <= 0:
                self.jump(um)

    def jump(self, um: UnitMap, avoid=None):
        old = self.unit
        n = _Fly(um, self.hue, avoid=avoid if avoid is not None else old)
        self.__dict__.update(n.__dict__)


class Firefly(Fun):
    key, label, category = "firefly", "Firefly", "Ambient"
    uses = ("speed", "rainbow", "firefly_count")
    help = ("Fireflies, each a little glow of 2–3 LEDs. They circle a fan ring, fade out, and pop up "
            "somewhere else: another fan, the GPU, your keyboard or mouse. Rainbow: each firefly gets its own color.")

    def on_layout(self, um):
        self.flies = []

    def render(self, ctx, leds):
        um = self.umap(leds)
        want = max(1, min(12, int(ctx.p.get("firefly_count", 3))))
        while len(self.flies) < want:
            self.flies.append(_Fly(um, random.random()))
        del self.flies[want:]
        sf = 0.4 + ctx.p.get("speed", 50) / 50
        for f in self.flies:
            f.step(um, ctx.dt, sf)
        out = [BLACK] * len(leds)
        for f in self.flies:
            flick = 0.7 + 0.3 * math.sin(ctx.t * 9 + f.ph)
            col = hsv(f.hue) if ctx.p.get("rainbow") else FIREFLY
            for i in um.leds_of.get(f.unit, ()):
                k = blob(leds[i], f.x) * f.alpha * flick
                if k > 0:
                    out[i] = maxc(out[i], scale(col, k))
        return out


class FireflyCatch(Fun):
    key, label = "firefly_catch", "Catch the Firefly"
    needs_input = True
    uses = ("speed",)
    help = ("GAME. Your mouse is the net: move it left↔right across the screen and a dim white glow sweeps "
            "across your fans. Put the net on the fan where the firefly is and CLICK to catch it. Hover too long "
            "and it flees! Score shows under the preview.")

    def on_layout(self, um):
        self.fly = _Fly(um, 0)
        self.score = self.miss = 0
        self.seen = None
        self.caught_at = self.miss_at = -9.0
        self.hover = 0.0

    def render(self, ctx, leds):
        um = self.umap(leds)
        inp = ctx.inp
        now = time.monotonic()
        px, _ = inp.pointer()
        net = um.nearest_unit(px)
        sf = 0.4 + ctx.p.get("speed", 50) / 50
        self.hover = self.hover + ctx.dt if net == self.fly.unit else 0.0
        if self.hover > 1.2 and self.fly.state == "fly":   # it noticed the net
            self.fly.state = "out"
            self.hover = 0.0
        self.fly.step(um, ctx.dt, sf, jumpy=0.6)
        if self.fly.alpha <= 0.05 and self.fly.state == "in" and self.fly.unit == net:
            self.fly.jump(um, avoid=net)

        if self.seen is None:
            self.seen = inp.clicks
        if inp.clicks != self.seen:
            self.seen = inp.clicks
            if net == self.fly.unit and self.fly.alpha > 0.4:
                self.score += 1
                self.caught_at = now
                self.fly.jump(um, avoid=net)
            else:
                self.miss += 1
                self.miss_at = now
        self.info = f"🪲 Caught: {self.score}    Missed: {self.miss}    (net on: fixture {net + 1})"

        out = [BLACK] * len(leds)
        miss = now - self.miss_at < 0.35
        for i in um.leds_of.get(net, ()):
            out[i] = (0.6, 0, 0) if miss else (0.09, 0.09, 0.1)
        flick = 0.7 + 0.3 * math.sin(ctx.t * 9)
        for i in um.leds_of.get(self.fly.unit, ()):
            k = blob(leds[i], self.fly.x) * self.fly.alpha * flick
            if k > 0:
                out[i] = maxc(out[i], scale(FIREFLY, k))
        age = now - self.caught_at
        if age < 1.5:   # celebration: a rainbow burst over everything
            k = math.exp(-age * 2.2)
            for i, l in enumerate(leds):
                out[i] = maxc(out[i], scale(hsv(l.pos + age * 0.8), k))
        return out


# ---- mouse / keyboard reactive ----------------------------------------------------------
class ScrollWheel(Fun):
    key, label = "scroll_wheel", "Scroll Wheel"
    needs_input = True
    uses = ("scroll_step",)
    help = ("Scroll your mouse wheel: every notch moves the light one LED around each fan ring and turns "
            "the color one step around the color wheel. It leaves a trail of every color it passed through. "
            "Scroll the other way to rewind.")

    def render(self, ctx, leds):
        inp = ctx.inp
        c = inp.scroll
        idle = time.monotonic() - inp.scroll_at
        fresh = math.exp(-idle * 0.7)
        step = max(1, ctx.p.get("scroll_step", 15)) / 360   # hue degrees per notch
        out = []
        for l in leds:
            if l.ring <= 1:
                out.append(scale(hsv(c * step), 0.35 + 0.65 * math.exp(-idle * 1.5)))
                continue
            r = ring_size(l)
            i = int(l.local * r + 0.5) % r
            d = (c - i) % r
            if d == 0:
                out.append(hsv(c * step))
            else:
                out.append(scale(hsv((c - d) * step), math.exp(-d * 0.45) * (0.25 + 0.75 * fresh)))
        self.info = f"Scroll position: {c:+d}"
        return out


class TypingSparks(Fun):
    key, label = "typing_sparks", "Typing Sparks"
    needs_input = True
    uses = ("rainbow",)
    help = ("Every keypress throws sparks onto random LEDs across the whole rig. Type faster and the sparks "
            "get hotter: blue → green → yellow → red. Your keyboard glows with your speed.")

    def on_layout(self, um):
        self.b = [0.0] * len(um.src)
        self.h = [0.0] * len(um.src)
        self.seen = None
        self.wpm = 0.0

    def render(self, ctx, leds):
        um = self.umap(leds)
        inp = ctx.inp
        n = len(leds)
        if self.seen is None:
            self.seen = inp.keys
        kps = inp.typing_speed()
        self.wpm += (kps * 12 - self.wpm) * min(1, ctx.dt * 3)
        heat = clamp(self.wpm / 90)
        hue = 0.66 * (1 - heat)
        new = min(10, inp.keys - self.seen)
        self.seen = inp.keys
        for _ in range(max(0, new)):
            for _ in range(5):
                i = random.randrange(n)
                self.b[i] = 1.0
                self.h[i] = random.random() if ctx.p.get("rainbow") else hue + random.uniform(-0.04, 0.04)
        d = math.exp(-ctx.dt * 2.5)
        out = []
        for i, l in enumerate(leds):
            self.b[i] *= d
            c = scale(hsv(self.h[i]), self.b[i])
            if l.kind == "keyboard":
                c = maxc(c, scale(hsv(hue), 0.05 + 0.5 * heat))
            out.append(c)
        self.info = f"⌨ {self.wpm:.0f} WPM"
        return out


class TypingMeter(Fun):
    key, label = "typing_meter", "Typing Speed Meter"
    needs_input = True
    uses = ()
    help = ("Every fan ring becomes a speedometer for your typing (0 → 100 WPM): rings fill green → yellow → "
            "red, and a white marker remembers your best recent burst.")

    def on_layout(self, um):
        self.wpm = 0.0
        self.best = 0.0

    def render(self, ctx, leds):
        self.umap(leds)
        inp = ctx.inp
        target = inp.typing_speed() * 12
        self.wpm += (target - self.wpm) * min(1, ctx.dt * 2)
        self.best = max(self.wpm, self.best - ctx.dt * 2)
        fill = clamp(self.wpm / 100)
        bestf = clamp(self.best / 100)
        out = []
        for l in leds:
            if l.ring <= 1:
                out.append(scale(hsv(0.33 * (1 - fill)), 0.1 + 0.9 * fill))
                continue
            if bestf > 0.03 and abs(l.local - bestf) < 0.5 / ring_size(l):
                out.append((1, 1, 1))
            elif l.local < fill:
                out.append(hsv(0.33 * (1 - l.local)))
            else:
                out.append((0.02, 0.02, 0.03))
        self.info = f"⌨ {self.wpm:.0f} WPM   (best {self.best:.0f})"
        return out


class MouseSpotlight(Fun):
    key, label = "mouse_spotlight", "Mouse Spotlight"
    needs_input = True
    uses = ("color2",)
    help = ("A spotlight follows your mouse: move left↔right and it slides across the fans; move up↕down "
            "and its color changes. Click to make it flash white. Color 2 is the background glow.")

    def reset(self, n):
        super().reset(n)
        self.x = 0.5
        self.seen = None
        self.flash_at = -9

    def render(self, ctx, leds):
        inp = ctx.inp
        px, py = inp.pointer()
        self.x += (px - self.x) * min(1, ctx.dt * 10)
        if self.seen is None:
            self.seen = inp.clicks
        if inp.clicks != self.seen:
            self.seen = inp.clicks
            self.flash_at = time.monotonic()
        fl = math.exp(-(time.monotonic() - self.flash_at) * 5)
        c = lerp(hsv(py), (1, 1, 1), fl)
        bg = scale(ctx.c2, 0.05)
        return [lerp(bg, c, math.exp(-((l.pos - self.x) / 0.09) ** 2)) for l in leds]


class MouseEnergy(Fun):
    key, label = "mouse_energy", "Mouse Energy"
    needs_input = True
    uses = ("color1",)
    help = ("Shake your mouse to charge the rig! Fast movement builds energy into a bright, racing rainbow "
            "storm. Stop moving and it calms down to a slow Color 1 breathe.")

    def reset(self, n):
        super().reset(n)
        self.prev = None
        self.energy = 0.0
        self.ph = 0.0

    def render(self, ctx, leds):
        px, py = ctx.inp.pointer()
        if self.prev is not None and ctx.dt > 0:
            sp = math.hypot(px - self.prev[0], py - self.prev[1]) / ctx.dt
            self.energy = clamp(self.energy * math.exp(-ctx.dt * 0.7) + sp * ctx.dt * 0.5)
        self.prev = (px, py)
        e = self.energy
        self.ph += ctx.dt * (0.05 + e * 2.5)
        calm = scale(ctx.c1, 0.2 + 0.15 * math.sin(ctx.t * 1.2))
        self.info = f"⚡ Energy {e * 100:.0f}%"
        return [lerp(calm, hsv(l.pos * 1.5 + l.local * 0.3 - self.ph), e) for l in leds]


class ClickFireworks(Fun):
    key, label = "click_fireworks", "Click Fireworks"
    needs_input = True
    uses = ("color1", "color2", "rainbow")
    help = ("Every mouse click launches a firework on a random fan. It bursts, then a shockwave rolls across "
            "the neighbouring fans. Left click = Color 1, right click = Color 2. Rainbow: random colors.")

    def reset(self, n):
        super().reset(n)
        self.seen = None
        self.bursts = []

    def render(self, ctx, leds):
        um = self.umap(leds)
        inp = ctx.inp
        now = time.monotonic()
        if self.seen is None:
            self.seen = inp.clicks
        for _ in range(min(5, inp.clicks - self.seen)):
            u = random.choice(um.units)
            if ctx.p.get("rainbow"):
                col = hsv(random.random())
            else:
                col = ctx.c2 if inp.click_button == 3 else ctx.c1
            self.bursts.append((now, um.pos[u], u, col))
        self.seen = inp.clicks
        self.bursts = [b for b in self.bursts if now - b[0] < 2.5]
        out = [BLACK] * len(leds)
        for t0, pos, u, col in self.bursts:
            age = now - t0
            r = age * 0.45
            for i, l in enumerate(leds):
                k = math.exp(-((abs(l.pos - pos) - r) / 0.04) ** 2) * math.exp(-age * 1.6)
                if l.unit == u:
                    k = max(k, math.exp(-age * 2.5) * (0.6 + 0.4 * math.sin(l.local * 18.8 + age * 25)))
                if age < 1.5 and random.random() < 0.015:
                    k = max(k, 0.7 * math.exp(-age))
                if k > 0.01:
                    out[i] = maxc(out[i], scale(col, k))
        return out


class Presence(Fun):
    key, label = "presence", "Presence"
    needs_input = True
    uses = ("color1", "color2")
    help = ("The lights know when you're there. While you work: a calm, flowing Color 1. Walk away and after "
            "30 s they slowly fall asleep into a gentle Color 2 breathe. Come back and a bright wave greets you.")

    def reset(self, n):
        super().reset(n)
        self.last_ptr = None
        self.move_at = time.monotonic()
        self.wake_at = -9.0
        self.was_idle = 0.0

    def render(self, ctx, leds):
        inp = ctx.inp
        now = time.monotonic()
        ptr = inp.pointer()
        if self.last_ptr is not None and ptr != self.last_ptr:
            self.move_at = now
        self.last_ptr = ptr
        idle = now - max(inp.key_at, inp.click_at, inp.scroll_at, self.move_at)
        if self.was_idle > 20 and idle < 0.5:
            self.wake_at = now
        self.was_idle = idle
        sleep = clamp((idle - 30) / 60)
        sleepy_b = 0.04 + 0.12 * (1 - math.cos(ctx.t * 0.8)) / 2
        age = now - self.wake_at
        out = []
        for l in leds:
            awake = scale(ctx.c1, 0.45 + 0.55 * (0.5 + 0.5 * math.sin(l.pos * 6.28 - ctx.t * 0.6)))
            c = lerp(awake, scale(ctx.c2, sleepy_b), sleep)
            if age < 1.8:
                c = addc(c, scale((1, 1, 1), math.exp(-((l.pos - age * 0.8) / 0.08) ** 2)))
            out.append(c)
        self.info = "🙂 You're here" if idle < 30 else f"💤 Away for {idle:.0f}s"
        return out


class ScrollPong(Fun):
    key, label = "scroll_pong", "Scroll Pong"
    needs_input = True
    uses = ("color1", "speed")
    help = ("A small ball of 2–3 LEDs bounces end to end through every fan, the GPU, mouse and keyboard. "
            "Scroll up to speed it up, down to slow it down, click to change its color.")

    def reset(self, n):
        super().reset(n)
        self.x = 0.0
        self.dir = 1
        self.seen_c = self.seen_s = None
        self.hue = None
        self.bounce_at = -9.0
        self.bounce_end = 0

    def render(self, ctx, leds):
        um = self.umap(leds)
        inp = ctx.inp
        if self.seen_c is None:
            self.seen_c, self.seen_s = inp.clicks, inp.scroll
        if inp.clicks != self.seen_c:
            self.seen_c = inp.clicks
            self.hue = random.random()
        boost = clamp(inp.scroll - self.seen_s, -6, 10)
        steps = len(um.steps)
        v = (6 + ctx.p.get("speed", 50) * 0.5) * (1.2 ** boost)
        self.x += self.dir * v * ctx.dt
        now = time.monotonic()
        if self.x >= steps - 1 or self.x <= 0:
            self.bounce_end = 0 if self.x <= 0 else 1
            self.x = clamp(self.x, 0, steps - 1)
            self.dir = -self.dir
            self.bounce_at = now
        col = hsv(self.hue) if self.hue is not None else ctx.c1
        out = [BLACK] * len(leds)
        for s in range(max(0, int(self.x) - 2), min(steps, int(self.x) + 3)):
            k = max(0.0, 1 - abs(s - self.x) / 1.6)
            for i in um.steps[s]:
                out[i] = maxc(out[i], scale(col, k))
        fl = math.exp(-(now - self.bounce_at) * 6)
        if fl > 0.02:
            end = um.steps[:3] if self.bounce_end == 0 else um.steps[-3:]
            for st in end:
                for i in st:
                    out[i] = maxc(out[i], (fl, fl, fl))
        self.info = f"🏓 Speed ×{1.2 ** boost:.1f}  (scroll to change)"
        return out


class Snake(Fun):
    key, label = "snake", "Snake"
    needs_input = True
    uses = ("color1", "color2", "speed")
    help = ("A snake slithers LED by LED through every fan, the GPU, mouse and keyboard, hunting its food "
            "(blinking Color 2). Every bite makes it longer. Scroll to boost it forward (or backward).")

    def on_layout(self, um):
        self.head = 0.0
        self.length = 4
        self.seen = None
        self.eat_at = -9.0
        self._place_food(um)

    def _place_food(self, um):
        steps = len(um.steps)
        h = int(self.head)
        body = {(h - k) % steps for k in range(self.length)}
        self.food = random.choice([s for s in range(steps) if s not in body] or [0])

    def render(self, ctx, leds):
        um = self.umap(leds)
        inp = ctx.inp
        steps = len(um.steps)
        if self.seen is None:
            self.seen = inp.scroll
        jump = inp.scroll - self.seen
        self.seen = inp.scroll
        self.head = (self.head + (3 + ctx.p.get("speed", 50) / 6) * ctx.dt + jump * 2) % steps
        h = int(self.head)
        now = time.monotonic()
        if h == self.food:
            self.length += 2
            self.eat_at = now
            if self.length > 40:
                self.length = 4
            self._place_food(um)
        out = [BLACK] * len(leds)
        blink = 0.4 + 0.6 * (0.5 + 0.5 * math.sin(ctx.t * 10))
        for i in um.steps[self.food]:
            out[i] = scale(ctx.c2, blink)
        for k in range(self.length):
            s = (h - k) % steps
            c = (1, 1, 1) if k == 0 else scale(ctx.c1, 1 - 0.8 * k / self.length)
            for i in um.steps[s]:
                out[i] = c
        fl = math.exp(-(now - self.eat_at) * 4)
        if fl > 0.05:
            out = [addc(c, scale(ctx.c2, 0.4 * fl)) for c in out]
        self.info = f"🐍 Length {self.length}"
        return out


# ---- system-reactive ----------------------------------------------------------------------
class SystemMonitor(Fun):
    key, label, category = "system_monitor", "System Monitor", "System"
    uses = ()
    help = ("Your fans become live gauges. Case fans + board = CPU load (each ring fills up), GPU fans = GPU "
            "load, keyboard + mouse = RAM use. Green → yellow → red as the load rises.")

    def reset(self, n):
        super().reset(n)
        self.v = {"cpu": 0.0, "gpu": 0.0, "ram": 0.0}

    def render(self, ctx, leds):
        tp = ctx.temps
        tp.poll()
        for k, val in (("cpu", tp.cpu_load), ("gpu", tp.gpu_load), ("ram", tp.ram)):
            self.v[k] += (val - self.v[k]) * min(1, ctx.dt * 3)
        out = []
        for l in leds:
            v = self.v["gpu" if l.kind == "gpu" else "ram" if l.kind in ("keyboard", "mouse") else "cpu"]
            if l.ring <= 1:
                out.append(scale(hsv(0.33 * (1 - v)), 0.25 + 0.75 * v))
            elif l.local <= max(v, 0.5 / ring_size(l)):
                out.append(hsv(0.33 * (1 - l.local)))
            else:
                out.append((0.015, 0.015, 0.02))
        self.info = f"CPU {self.v['cpu'] * 100:.0f}%   GPU {self.v['gpu'] * 100:.0f}%   RAM {self.v['ram'] * 100:.0f}%"
        return out


class Heartbeat(Fun):
    key, label, category = "heartbeat", "Heartbeat", "System"
    uses = ("color1",)
    help = "A lub-dub heartbeat through every light. It beats faster the harder your CPU works (50 → 160 BPM)."

    def reset(self, n):
        super().reset(n)
        self.ph = 0.0
        self.bpm = 60.0

    def render(self, ctx, leds):
        ctx.temps.poll()
        self.bpm += (50 + ctx.temps.cpu_load * 110 - self.bpm) * min(1, ctx.dt)
        self.ph += ctx.dt * self.bpm / 60
        out = []
        for l in leds:
            x = (self.ph - l.pos * 0.06) % 1.0
            p = math.exp(-(x / 0.045) ** 2) + math.exp(-((x - 1) / 0.045) ** 2) \
                + 0.6 * math.exp(-((x - 0.17) / 0.05) ** 2)
            out.append(scale(ctx.c1, 0.06 + 0.94 * min(1, p)))
        self.info = f"❤ {self.bpm:.0f} BPM"
        return out


# ---- ambient --------------------------------------------------------------------------------
class Raindrops(Fun):
    key, label, category = "raindrops", "Raindrops", "Ambient"
    uses = ("color1", "speed", "rainbow")
    help = "Raindrops land on random LEDs and ripple out around the fan ring like drops in a pond."

    def reset(self, n):
        super().reset(n)
        self.drops = []

    def render(self, ctx, leds):
        um = self.umap(leds)
        if random.random() < ctx.dt * (1 + ctx.p.get("speed", 50) / 12):
            u = random.choice(um.units)
            self.drops.append((ctx.t, u, random.random(), random.random()))
        self.drops = [d for d in self.drops if ctx.t - d[0] < 2]
        out = [scale(ctx.c1, 0.02)] * len(leds)
        for t0, u, x, hue in self.drops:
            age = ctx.t - t0
            col = hsv(hue) if ctx.p.get("rainbow") else ctx.c1
            for i in um.leds_of[u]:
                l = leds[i]
                if l.ring <= 1:
                    k = math.exp(-age * 3)
                else:
                    d = ring_dist(l.local, x) * ring_size(l)
                    k = math.exp(-((d - age * 5) / 0.8) ** 2) * math.exp(-age * 1.8)
                out[i] = maxc(out[i], scale(col, k))
        return out


class Lightning(Fun):
    key, label, category = "lightning", "Lightning Storm", "Ambient"
    uses = ("color2", "speed")
    help = "A dark, brooding sky (Color 2) torn by sudden lightning strikes that flicker across random fans."

    def reset(self, n):
        super().reset(n)
        self.strikes = []
        self.next = 1.0

    def render(self, ctx, leds):
        um = self.umap(leds)
        self.next -= ctx.dt * (0.5 + ctx.p.get("speed", 50) / 40)
        if self.next <= 0:
            self.next = random.uniform(1.0, 5.0)
            units = random.sample(um.units, k=min(len(um.units), random.randint(1, 4)))
            self.strikes.append((ctx.t, set(units), random.random()))
        self.strikes = [s for s in self.strikes if ctx.t - s[0] < 1.2]
        sky = 0.05 + 0.03 * math.sin(ctx.t * 0.4)
        out = [scale(ctx.c2, sky)] * len(leds)
        for t0, units, seed in self.strikes:
            age = ctx.t - t0
            # Two or three quick flickers, then a fading afterglow.
            fl = 1.0 if (age < 0.06 or 0.12 < age < 0.18 or (seed > 0.5 and 0.26 < age < 0.3)) else 0.0
            glow = math.exp(-age * 4) * 0.4
            k = max(fl, glow)
            for u in units:
                for i in um.leds_of[u]:
                    out[i] = maxc(out[i], scale((0.85, 0.9, 1.0), k))
        return out


class Aurora(Fun):
    key, label, category = "aurora", "Aurora", "Ambient"
    uses = ("speed",)
    help = "Northern lights: slow curtains of green, teal and violet drifting across the rig."

    def render(self, ctx, leds):
        t = ctx.phase * 2
        out = []
        for l in leds:
            h = 0.36 + 0.2 * math.sin(l.pos * 3.1 + t * 0.6) + 0.07 * math.sin(l.local * 6.28 + t + l.unit)
            v = 0.25 + 0.75 * (0.5 + 0.5 * math.sin(l.pos * 5 - t * 0.9 + 2 * math.sin(t * 0.3)))
            out.append(hsv(h, 0.85, v))
        return out


class MeteorShower(Fun):
    key, label, category = "meteors", "Meteor Shower", "Ambient"
    uses = ("speed", "rainbow")
    help = "Meteors with long glowing tails streak LED by LED through the fans, GPU and keyboard."

    def reset(self, n):
        super().reset(n)
        self.m = []

    def render(self, ctx, leds):
        um = self.umap(leds)
        steps = len(um.steps)
        if random.random() < ctx.dt * (0.5 + ctx.p.get("speed", 50) / 25):
            self.m.append([random.uniform(0, steps * 0.6), random.uniform(25, 60), random.random()])
        for m in self.m:
            m[0] += m[1] * ctx.dt
        self.m = [m for m in self.m if m[0] - 12 < steps]
        out = [BLACK] * len(leds)
        for head, _v, hue in self.m:
            col = hsv(hue) if ctx.p.get("rainbow") else (0.8, 0.85, 1.0)
            for k in range(12):
                s = int(head) - k
                if 0 <= s < steps:
                    c = (1, 1, 1) if k == 0 else scale(col, math.exp(-k * 0.3))
                    for i in um.steps[s]:
                        out[i] = maxc(out[i], c)
        return out


FUN_EFFECTS = (Firefly, FireflyCatch, ScrollWheel, TypingSparks, TypingMeter, MouseSpotlight,
               MouseEnergy, ClickFireworks, Presence, ScrollPong, Snake, SystemMonitor, Heartbeat,
               Raindrops, Lightning, Aurora, MeteorShower)
