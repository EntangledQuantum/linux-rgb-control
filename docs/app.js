/* RGB Control landing page.
 * The effects below are ports of rgbctl/effects.py and rgbctl/effects_fun.py: same math,
 * same LED model (pos 0..1 along the rig, unit = fixture, local 0..1 around its ring).
 * Plain JS, no dependencies. */
'use strict';
(() => {
  // ======================================================================================
  // helpers (port of the colour helpers in effects.py)
  // ======================================================================================
  const TAU = Math.PI * 2;
  const BLACK = [0, 0, 0];
  const WHITE = [1, 1, 1];
  const FIREFLY = [0.72, 1.0, 0.12];
  const mod = (a, n) => ((a % n) + n) % n;
  const clamp = (v, lo = 0, hi = 1) => (v < lo ? lo : v > hi ? hi : v);
  const rand = (a, b) => a + Math.random() * (b - a);
  const choice = (arr) => arr[Math.floor(Math.random() * arr.length)];
  const now = () => performance.now() / 1000;
  function hsv(h, s = 1, v = 1) {
    h = mod(h, 1);
    const i = Math.floor(h * 6), f = h * 6 - i;
    const p = v * (1 - s), q = v * (1 - s * f), t = v * (1 - s * (1 - f));
    switch (i % 6) {
      case 0: return [v, t, p];
      case 1: return [q, v, p];
      case 2: return [p, v, t];
      case 3: return [p, q, v];
      case 4: return [t, p, v];
      default: return [v, p, q];
    }
  }
  const lerp = (a, b, t) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
  const scale = (c, k) => [c[0] * k, c[1] * k, c[2] * k];
  const maxc = (a, b) => [Math.max(a[0], b[0]), Math.max(a[1], b[1]), Math.max(a[2], b[2])];
  const addc = (a, b) => [Math.min(1, a[0] + b[0]), Math.min(1, a[1] + b[1]), Math.min(1, a[2] + b[2])];
  const tri = (v) => 1 - Math.abs(2 * mod(v, 1) - 1);
  const speedToRate = (s) => { s = clamp(s, 0, 100) / 100; return 0.02 + s * s * 1.6; };
  const ringDist = (a, b) => { const d = mod(Math.abs(a - b), 1); return Math.min(d, 1 - d); };
  const ringSize = (l) => (l.kind === 'fan' ? l.ring : Math.min(l.ring, 24));
  function blob(l, x, width = 1.4) {
    if (l.ring <= 1) return 1;
    const d = ringDist(l.local, x) * ringSize(l);
    return Math.max(0, 1 - d / width);
  }
  const hexToRgb = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
  const gauss = (x) => Math.exp(-x * x);

  const reducedMQ = window.matchMedia('(prefers-reduced-motion: reduce)');
  let reduced = reducedMQ.matches;
  const live = document.getElementById('live');
  const announce = (msg) => { if (live) { live.textContent = ''; setTimeout(() => { live.textContent = msg; }, 30); } };

  // ======================================================================================
  // the rig: a stylised PC. Every LED gets the same fields the app's layout builder gives it.
  // ======================================================================================
  const VW = 900, VH = 680, LPF = 12;
  const GLASS = { x: 112, y: 28, w: 676, h: 476 };

  function buildRig() {
    const fx = [];
    [130, 268, 406].forEach((cy, i) => fx.push({ type: 'fan', kind: 'fan', name: `front fan ${i + 1}`, cx: 190, cy, r: 54, frame: 132, blades: 7, spin: 1 }));
    [385, 540, 695].forEach((cx, i) => fx.push({ type: 'fan', kind: 'gpu', name: `GPU fan ${i + 1}`, cx, cy: 426, r: 33, frame: 0, blades: 9, spin: i % 2 ? -1.3 : 1.3 }));
    fx.push({ type: 'ring', kind: 'board', name: 'CPU pump', cx: 470, cy: 228, r: 29, n: 12 });
    fx.push({ type: 'ram', kind: 'board', name: 'RAM', x0: 568, y0: 150, y1: 292, sticks: 4, per: 6, pitch: 17 });
    [440, 580].forEach((cx, i) => fx.push({ type: 'fan', kind: 'fan', name: `top fan ${i + 1}`, cx, cy: 72, r: 32, frame: 84, blades: 7, spin: 1 }));
    fx.push({ type: 'fan', kind: 'fan', name: 'rear fan', cx: 715, cy: 150, r: 44, frame: 110, blades: 7, spin: -1 });
    fx.push({ type: 'keyboard', kind: 'keyboard', name: 'keyboard', slots: 3, x0: 136, y0: 567, w: 508, h: 94 });
    fx.push({ type: 'mouse', kind: 'mouse', name: 'mouse', cx: 722, cy: 612 });

    const total = fx.reduce((s, f) => s + (f.slots || 1), 0);
    const leds = [], units = [];
    let slot = 0;
    fx.forEach((f, unit) => {
      const slots = f.slots || 1;
      const L = (o) => leds.push(Object.assign({ unit, kind: f.kind, rnd: Math.random() }, o));
      if (f.type === 'fan') {
        const n = LPF;
        for (let k = 0; k < n; k++) {
          const local = k / n, a = -Math.PI / 2 + local * TAU;
          L({ pos: (slot + 0.5) / total, local, ring: n, x: f.cx + f.r * Math.cos(a), y: f.cy + f.r * Math.sin(a),
            d: { t: 'arc', cx: f.cx, cy: f.cy, r: f.r, a, span: (TAU / n) * 0.8, w: f.r * 0.16 }, R: f.r * 0.36, ga: 0.9 });
        }
        const h = f.frame ? f.frame / 2 : f.r * 1.3;
        units.push({ name: f.name, kind: f.kind, cx: f.cx, cy: f.cy, box: [f.cx - h, f.cy - h, f.cx + h, f.cy + h] });
      } else if (f.type === 'ring') {
        for (let k = 0; k < f.n; k++) {
          const local = (k + 0.5) / f.n, a = -Math.PI / 2 + local * TAU;
          L({ pos: (slot + local) / total, local, ring: f.n, x: f.cx + f.r * Math.cos(a), y: f.cy + f.r * Math.sin(a),
            d: { t: 'arc', cx: f.cx, cy: f.cy, r: f.r, a, span: (TAU / f.n) * 0.78, w: 5 }, R: 11, ga: 0.85 });
        }
        units.push({ name: f.name, kind: f.kind, cx: f.cx, cy: f.cy, box: [f.cx - 44, f.cy - 44, f.cx + 44, f.cy + 44] });
      } else if (f.type === 'ram') {
        const n = f.sticks * f.per, seg = (f.y1 - f.y0 - 16) / f.per;
        for (let s = 0; s < f.sticks; s++) {
          for (let j = 0; j < f.per; j++) {
            const local = (s * f.per + j + 0.5) / n;
            const x = f.x0 + s * f.pitch, y = f.y0 + 8 + j * seg;
            L({ pos: (slot + local) / total, local, ring: n, x, y: y + seg / 2,
              d: { t: 'rect', x: x - 2.5, y: y + 1.5, w: 5, h: seg - 3 }, R: 9, ga: 0.6 });
          }
        }
        units.push({ name: f.name, kind: f.kind, cx: f.x0 + 1.5 * f.pitch, cy: (f.y0 + f.y1) / 2, box: [f.x0 - 10, f.y0, f.x0 + 3 * f.pitch + 10, f.y1] });
      } else if (f.type === 'keyboard') {
        const rows = [Array(18).fill(1), Array(18).fill(1), Array(18).fill(1), Array(18).fill(1), [1, 1, 1, 7, 1, 1, 1, 1, 1, 1, 1, 1]];
        const px = f.w / 18, py = f.h / 5, n = rows.reduce((s, r) => s + r.length, 0);
        rows.forEach((row, ri) => {
          let c = 0;
          row.forEach((wu) => {
            const center = c + (wu - 1) / 2, local = center / 17;
            const x = f.x0 + c * px + 2, y = f.y0 + ri * py + 2, w = wu * px - 4, h = py - 4;
            L({ pos: (slot + local * slots) / total, local, ring: n, x: x + w / 2, y: y + h / 2,
              d: { t: 'key', x, y, w, h }, R: 12, ga: 0.42 });
            c += wu;
          });
        });
        units.push({ name: f.name, kind: f.kind, cx: f.x0 + f.w / 2, cy: f.y0 + f.h / 2, box: [f.x0 - 12, f.y0 - 12, f.x0 + f.w + 12, f.y0 + f.h + 12] });
        f.rows = rows;
      } else if (f.type === 'mouse') {
        const cx = f.cx, cy = f.cy;
        const parts = [
          { local: 1 / 6, x: cx, y: cy - 36, d: { t: 'rect', x: cx - 3, y: cy - 44, w: 6, h: 15 }, R: 10 },
          { local: 3 / 6, x: cx, y: cy + 16, d: { t: 'dot', x: cx, y: cy + 16, r: 6 }, R: 14 },
          { local: 5 / 6, x: cx, y: cy + 44, d: { t: 'arc', cx, cy: cy + 18, r: 25, a: Math.PI / 2, span: Math.PI * 0.72, w: 3.2 }, R: 18 },
        ];
        parts.forEach((p) => L({ pos: (slot + p.local) / total, local: p.local, ring: 3, x: p.x, y: p.y, d: p.d, R: p.R, ga: 0.8 }));
        units.push({ name: f.name, kind: f.kind, cx, cy, box: [cx - 34, cy - 54, cx + 34, cy + 54] });
      }
      slot += slots;
    });
    return { fixtures: fx, leds, units, total };
  }

  // Port of UnitMap: groups LEDs by fixture and builds the LED-by-LED path through the rig.
  class UnitMap {
    constructor(rig) {
      const leds = rig.leds;
      this.rig = rig;
      this.leds_of = [];
      leds.forEach((l, i) => { (this.leds_of[l.unit] = this.leds_of[l.unit] || []).push(i); });
      this.units = this.leds_of.map((_, u) => u);
      this.pos = this.units.map((u) => this.leds_of[u].reduce((s, i) => s + leds[i].pos, 0) / this.leds_of[u].length);
      this.kind = this.units.map((u) => leds[this.leds_of[u][0]].kind);
      this.names = rig.units.map((u) => u.name);
      const steps = [];
      for (const u of this.units) {
        const ix = this.leds_of[u];
        if (this.kind[u] === 'keyboard') {
          const cols = new Map();
          for (const i of ix) {
            const c = Math.round(leds[i].local * 21);
            if (!cols.has(c)) cols.set(c, []);
            cols.get(c).push(i);
          }
          [...cols.keys()].sort((a, b) => a - b).forEach((k) => steps.push(cols.get(k)));
        } else {
          ix.slice().sort((a, b) => leds[a].local - leds[b].local).forEach((i) => steps.push([i]));
        }
      }
      this.steps = steps;
    }
    nearest_unit(x) {
      let best = 0, bd = Infinity;
      for (const u of this.units) { const d = Math.abs(this.pos[u] - x); if (d < bd) { bd = d; best = u; } }
      return best;
    }
    // Browser addition: the fixture under (or closest to) a point on the canvas.
    nearestXY(x, y) {
      let best = 0, bd = Infinity;
      this.rig.units.forEach((u, i) => {
        const [x0, y0, x1, y1] = u.box;
        const dx = Math.max(x0 - x, 0, x - x1), dy = Math.max(y0 - y, 0, y - y1);
        const d = Math.hypot(dx, dy) + Math.hypot(u.cx - x, u.cy - y) * 0.001;
        if (d < bd) { bd = d; best = i; }
      });
      return best;
    }
  }

  // ======================================================================================
  // effects (port of effects.py + effects_fun.py)
  // ======================================================================================
  const EFFECTS = {};
  const reg = (cls) => { EFFECTS[cls.key] = cls; return cls; };

  class Effect {
    constructor() { this.info = ''; }
    reset() {}
  }
  Effect.uses = ['color1', 'speed'];
  Effect.cat = 'Classic';
  Effect.input = null; // which browser inputs it reads: wheel / pointer / click / keys

  const def = (cls, key, label, cat, uses, help, extra = {}) => {
    Object.assign(cls, { key, label, cat, uses, help }, extra);
    return reg(cls);
  };

  // ---- classic ------------------------------------------------------------------------
  def(class extends Effect { render(c, leds) { return leds.map(() => c.c1); } },
    'static', 'Static', 'Classic', ['color1'], 'One solid color on every fan.');

  def(class extends Effect {
    render(c, leds) {
      const b = Math.pow((1 - Math.cos(TAU * c.phase)) / 2, 1.6);
      const col = c.p.rainbow ? hsv(Math.floor(c.phase) * 0.17) : c.c1;
      const out = scale(col, b);
      return leds.map(() => out);
    }
  }, 'breathing', 'Breathing', 'Classic', ['color1', 'speed', 'rainbow'], "Fades in and out together. 'Rainbow' changes color each breath.");

  def(class extends Effect { render(c, leds) { const col = hsv(c.phase * 0.25); return leds.map(() => col); } },
    'color_cycle', 'Color Cycle', 'Classic', ['speed'], 'All fans shift through the spectrum together.');

  def(class extends Effect { render(c, leds) { const ph = c.phase * 0.5; return leds.map((l) => hsv(l.pos - ph)); } },
    'rainbow_wave', 'Rainbow Wave', 'Classic', ['speed', 'reverse'], 'A rainbow that flows across all fans.');

  def(class extends Effect {
    render(c, leds) { const ph = c.phase * 0.25; return leds.map((l) => lerp(c.c1, c.c2, tri(l.pos * 0.5 + ph))); }
  }, 'gradient', 'Gradient', 'Classic', ['color1', 'color2', 'speed', 'reverse'], 'Blend from Color 1 to Color 2 across the rig, slowly drifting.');

  def(class extends Effect {
    render(c, leds) {
      const ph = c.phase * 3, on = mod(ph, 1) < 0.18;
      const col = c.p.rainbow ? hsv(Math.floor(ph) * 0.13) : c.c1;
      return leds.map(() => (on ? col : BLACK));
    }
  }, 'strobe', 'Strobe', 'Classic', ['color1', 'speed', 'rainbow'], 'Sharp flashes. (Flashing light: lower the speed if that bothers you.)');

  def(class extends Effect {
    render(c, leds) {
      const head = mod(c.phase * 0.5, 1), bg = scale(c.c2, 0.06);
      return leds.map((l) => {
        const d = mod(head - l.pos, 1), k = Math.exp(-d * 9);
        return lerp(bg, c.p.rainbow ? hsv(head + 0.3 * d) : c.c1, k);
      });
    }
  }, 'comet', 'Comet', 'Classic', ['color1', 'color2', 'speed', 'rainbow', 'reverse'], 'A bright head with a fading tail runs from fan to fan over a Color 2 background.');

  def(class extends Effect {
    render(c, leds) {
      const ph = mod(c.phase * 1.5, 1), side = ph < 0.5 ? 0 : 1, local = mod(ph, 0.5) * 2;
      const on = local < 0.15 || (local > 0.25 && local < 0.4);
      const col = side === 0 ? [1, 0, 0] : [0, 0.2, 1];
      return leds.map((l) => (on && l.unit % 2 === side ? col : BLACK));
    }
  }, 'police', 'Police', 'Classic', ['speed'], 'Red and blue double flashes, alternating between fans.');

  // ---- fan rings ----------------------------------------------------------------------
  def(class extends Effect {
    render(c, leds) {
      const head = mod(c.phase, 1), bg = scale(c.c2, 0.08);
      return leds.map((l) => {
        const d = mod(head - l.local, 1), k = Math.exp(-d * 6);
        const col = c.p.rainbow ? hsv(l.unit / Math.max(1, c.units) + c.phase * 0.05) : c.c1;
        return lerp(bg, col, k);
      });
    }
  }, 'spin', 'Spin', 'Fan rings', ['color1', 'color2', 'speed', 'rainbow', 'reverse'], 'A light spins around each fan ring, LED by LED.');

  def(class extends Effect { render(c, leds) { return leds.map((l) => hsv(l.local + c.phase * 0.5 + l.unit * 0.08)); } },
    'rainbow_ring', 'Rainbow Ring', 'Fan rings', ['speed', 'reverse'], 'Every fan ring shows a full rainbow that rotates, LED by LED.');

  def(class extends Effect {
    render(c, leds) {
      const step = Math.floor(c.phase * 4), bg = scale(c.c2, 0.15);
      return leds.map((l) => {
        const i = Math.round(l.local * c.lpf), on = mod(i + step, 3) === 0;
        const col = c.p.rainbow ? hsv(l.unit * 0.1 + c.phase * 0.05) : c.c1;
        return on ? col : bg;
      });
    }
  }, 'marquee', 'Marquee', 'Fan rings', ['color1', 'color2', 'speed', 'rainbow', 'reverse'], 'Theatre-style chasing lights: every third LED lit, marching around each fan.');

  // ---- ambient ------------------------------------------------------------------------
  const FIRE_PAL = [[0, 0, 0], [0.5, 0, 0], [1, 0.15, 0], [1, 0.45, 0], [1, 0.8, 0.2]];
  def(class extends Effect {
    pal(h) { h = clamp(h, 0, 0.999) * (FIRE_PAL.length - 1); const i = Math.floor(h); return lerp(FIRE_PAL[i], FIRE_PAL[i + 1], h - i); }
    render(c, leds) {
      const t = c.t * (0.6 + c.p.speed / 40);
      return leds.map((l) => {
        const s = l.unit * 7.13 + l.rnd * 3;
        const h = 0.55 + 0.18 * Math.sin(t * 3.1 + s) + 0.12 * Math.sin(t * 7.7 + s * 2.3) + 0.08 * Math.sin(t * 13.3 + s * 5.1) + rand(-0.06, 0.06);
        return this.pal(h);
      });
    }
  }, 'fire', 'Fire', 'Ambient', ['speed'], 'Flickering flames, each fan burning on its own.');

  def(class extends Effect {
    reset(n) { this.b = new Float32Array(n); this.hue = new Float32Array(n); }
    render(c, leds) {
      const n = leds.length;
      if (!this.b || this.b.length !== n) this.reset(n);
      const decay = Math.exp(-c.dt * 3), chance = c.dt * (0.15 + speedToRate(c.p.speed) * 1.5), bg = scale(c.c2, 0.12);
      const out = new Array(n);
      for (let i = 0; i < n; i++) {
        this.b[i] *= decay;
        if (Math.random() < chance) { this.b[i] = 1; this.hue[i] = Math.random(); }
        out[i] = lerp(bg, c.p.rainbow ? hsv(this.hue[i]) : c.c1, this.b[i]);
      }
      return out;
    }
  }, 'twinkle', 'Starlight', 'Ambient', ['color1', 'color2', 'speed', 'rainbow'], 'Random sparkles of Color 1 over a dim Color 2 glow.');

  class Fly {
    constructor(um, hue, avoid = null) {
      const choices = um.units.filter((u) => u !== avoid);
      this.unit = choice(choices.length ? choices : um.units);
      this.x = Math.random();
      this.v = choice([-1, 1]) * rand(0.25, 0.6);
      this.life = rand(2.5, 6);
      this.alpha = 0;
      this.state = 'in';
      this.hue = hue;
      this.ph = Math.random() * 6.28;
    }
    step(um, dt, sf, jumpy = 1) {
      this.x = mod(this.x + this.v * dt * sf, 1);
      if (Math.random() < dt * 0.4) this.v = -this.v;
      if (this.state === 'in') {
        this.alpha = Math.min(1, this.alpha + dt * 3);
        if (this.alpha >= 1) this.state = 'fly';
      } else if (this.state === 'fly') {
        this.life -= dt * sf * jumpy;
        if (this.life <= 0) this.state = 'out';
      } else {
        this.alpha -= dt * 3;
        if (this.alpha <= 0) this.jump(um);
      }
    }
    jump(um, avoid = null) { Object.assign(this, new Fly(um, this.hue, avoid !== null ? avoid : this.unit)); }
  }

  def(class extends Effect {
    reset() { this.flies = []; }
    render(c, leds) {
      const um = c.um, want = clamp(Math.floor(c.p.firefly_count), 1, 12);
      while (this.flies.length < want) this.flies.push(new Fly(um, Math.random()));
      this.flies.length = want;
      const sf = 0.4 + c.p.speed / 50;
      for (const f of this.flies) f.step(um, c.dt, sf);
      const out = leds.map(() => BLACK);
      for (const f of this.flies) {
        const flick = 0.7 + 0.3 * Math.sin(c.t * 9 + f.ph), col = c.p.rainbow ? hsv(f.hue) : FIREFLY;
        for (const i of um.leds_of[f.unit]) {
          const k = blob(leds[i], f.x) * f.alpha * flick;
          if (k > 0) out[i] = maxc(out[i], scale(col, k));
        }
      }
      return out;
    }
  }, 'firefly', 'Firefly', 'Ambient', ['speed', 'rainbow', 'firefly_count'],
  'Fireflies, each a little glow of 2–3 LEDs. They circle a fan ring, fade out, and pop up somewhere else: another fan, the GPU, your keyboard or mouse. Rainbow: each firefly gets its own color.');

  def(class extends Effect {
    reset() { this.drops = []; }
    render(c, leds) {
      const um = c.um;
      if (Math.random() < c.dt * (1 + c.p.speed / 12)) this.drops.push([c.t, choice(um.units), Math.random(), Math.random()]);
      this.drops = this.drops.filter((d) => c.t - d[0] < 2);
      const out = leds.map(() => scale(c.c1, 0.02));
      for (const [t0, u, x, hue] of this.drops) {
        const age = c.t - t0, col = c.p.rainbow ? hsv(hue) : c.c1;
        for (const i of um.leds_of[u]) {
          const l = leds[i];
          let k;
          if (l.ring <= 1) k = Math.exp(-age * 3);
          else { const d = ringDist(l.local, x) * ringSize(l); k = gauss((d - age * 5) / 0.8) * Math.exp(-age * 1.8); }
          out[i] = maxc(out[i], scale(col, k));
        }
      }
      return out;
    }
  }, 'raindrops', 'Raindrops', 'Ambient', ['color1', 'speed', 'rainbow'], 'Raindrops land on random LEDs and ripple out around the fan ring like drops in a pond.');

  def(class extends Effect {
    reset() { this.strikes = []; this.next = 1; }
    render(c, leds) {
      const um = c.um;
      this.next -= c.dt * (0.5 + c.p.speed / 40);
      if (this.next <= 0) {
        this.next = rand(1, 5);
        const pool = um.units.slice().sort(() => Math.random() - 0.5);
        this.strikes.push([c.t, pool.slice(0, Math.min(pool.length, 1 + Math.floor(Math.random() * 4))), Math.random()]);
      }
      this.strikes = this.strikes.filter((s) => c.t - s[0] < 1.2);
      const sky = 0.05 + 0.03 * Math.sin(c.t * 0.4);
      const out = leds.map(() => scale(c.c2, sky));
      for (const [t0, units, seed] of this.strikes) {
        const age = c.t - t0;
        const fl = age < 0.06 || (age > 0.12 && age < 0.18) || (seed > 0.5 && age > 0.26 && age < 0.3) ? 1 : 0;
        const k = Math.max(fl, Math.exp(-age * 4) * 0.4);
        for (const u of units) for (const i of um.leds_of[u]) out[i] = maxc(out[i], scale([0.85, 0.9, 1.0], k));
      }
      return out;
    }
  }, 'lightning', 'Lightning Storm', 'Ambient', ['color2', 'speed'], 'A dark, brooding sky (Color 2) torn by sudden lightning strikes that flicker across random fans.');

  def(class extends Effect {
    render(c, leds) {
      const t = c.phase * 2;
      return leds.map((l) => {
        const h = 0.36 + 0.2 * Math.sin(l.pos * 3.1 + t * 0.6) + 0.07 * Math.sin(l.local * 6.28 + t + l.unit);
        const v = 0.25 + 0.75 * (0.5 + 0.5 * Math.sin(l.pos * 5 - t * 0.9 + 2 * Math.sin(t * 0.3)));
        return hsv(h, 0.85, v);
      });
    }
  }, 'aurora', 'Aurora', 'Ambient', ['speed'], 'Northern lights: slow curtains of green, teal and violet drifting across the rig.');

  def(class extends Effect {
    reset() { this.m = []; }
    render(c, leds) {
      const um = c.um, steps = um.steps.length;
      if (Math.random() < c.dt * (0.5 + c.p.speed / 25)) this.m.push([rand(0, steps * 0.6), rand(25, 60), Math.random()]);
      for (const m of this.m) m[0] += m[1] * c.dt;
      this.m = this.m.filter((m) => m[0] - 12 < steps);
      const out = leds.map(() => BLACK);
      for (const [head, , hue] of this.m) {
        const col = c.p.rainbow ? hsv(hue) : [0.8, 0.85, 1.0];
        for (let k = 0; k < 12; k++) {
          const s = Math.floor(head) - k;
          if (s >= 0 && s < steps) {
            const cc = k === 0 ? WHITE : scale(col, Math.exp(-k * 0.3));
            for (const i of um.steps[s]) out[i] = maxc(out[i], cc);
          }
        }
      }
      return out;
    }
  }, 'meteors', 'Meteor Shower', 'Ambient', ['speed', 'rainbow'], 'Meteors with long glowing tails streak LED by LED through the fans, GPU and keyboard.');

  // ---- music --------------------------------------------------------------------------
  const MUSIC = ['sensitivity'];
  def(class extends Effect {
    render(c, leds) {
      const a = c.audio, fl = c.p.music_floor / 100, b = fl + (1 - fl) * Math.pow(a.level, 1.2);
      return leds.map((l) => scale(c.p.rainbow ? hsv(c.t * 0.05 + l.pos * 0.5 + a.bass * 0.25) : lerp(c.c1, c.c2, a.bass), b));
    }
  }, 'music', 'Pulse', 'Music', ['color1', 'color2', 'rainbow', ...MUSIC], 'Everything pulses with the volume. Bass pushes the color from Color 1 toward Color 2.');

  def(class extends Effect {
    reset() { this.seen = -1; this.hue = Math.random(); this.flash = 0; this.flip = false; }
    render(c, leds) {
      const a = c.audio;
      if (a.beats !== this.seen) {
        if (this.seen !== -1) { this.hue = mod(this.hue + 0.618, 1); this.flip = !this.flip; this.flash = 1; }
        this.seen = a.beats;
      }
      this.flash *= Math.exp(-c.dt * 5);
      const fl = c.p.music_floor / 100, b = Math.max(this.flash, fl + 0.55 * a.bass);
      return leds.map((l) => {
        const col = c.p.rainbow ? hsv(this.hue + (l.unit % 4) * 0.25) : (this.flip !== (l.unit % 2 === 1) ? c.c2 : c.c1);
        return scale(col, b);
      });
    }
  }, 'music_beat', 'Beat Party', 'Music', ['color1', 'color2', 'rainbow', ...MUSIC],
  'Every beat flashes the whole rig and changes the colors. Rainbow on: new colors on every beat, different on each fan. Rainbow off: swaps between Color 1 and Color 2.');

  def(class extends Effect {
    render(c, leds) {
      const bands = c.audio.bands, nb = bands.length, units = Math.max(1, c.units), rev = c.p.reverse;
      return leds.map((l) => {
        const u = rev ? units - 1 - l.unit : l.unit;
        const lo = Math.floor((u * nb) / units), hi = Math.max(lo + 1, Math.floor(((u + 1) * nb) / units));
        let v = 0;
        for (let i = lo; i < hi; i++) v = Math.max(v, bands[i]);
        const frac = u / Math.max(1, units - 1);
        const base = c.p.rainbow ? hsv(frac * 0.78) : lerp(c.c1, c.c2, v);
        const k = l.local <= v ? 1 : Math.max(0.04, c.p.music_floor / 100);
        return scale(base, k * (0.25 + 0.75 * v));
      });
    }
  }, 'music_spectrum', 'Spectrum', 'Music', ['color1', 'color2', 'rainbow', 'reverse', ...MUSIC],
  'A graphic equalizer across your fans: bass on one end, treble on the other. Each fan ring fills up with its band’s level. Rainbow on: colored by frequency (red bass → violet treble).');

  def(class extends Effect {
    reset() { this.seen = -1; this.waves = []; this.hue = Math.random(); }
    render(c, leds) {
      const a = c.audio;
      if (a.beats !== this.seen) {
        if (this.seen !== -1) { this.hue = mod(this.hue + 0.618, 1); this.waves.push([c.t, this.hue]); }
        this.seen = a.beats;
      }
      const v = 0.4 + speedToRate(c.p.speed) * 1.5;
      this.waves = this.waves.filter((w) => (c.t - w[0]) * v < 1.4);
      const glow = scale(c.c2, 0.05 + 0.3 * a.treble), rev = c.p.reverse;
      return leds.map((l) => {
        const pos = rev ? 1 - l.pos : l.pos;
        let col = glow;
        for (const [t0, hue] of this.waves) {
          const d = pos - (c.t - t0) * v, k = gauss(d / 0.12) * Math.exp(-(c.t - t0) * 0.8);
          if (k > 0.01) col = maxc(col, scale(c.p.rainbow ? hsv(hue) : c.c1, k));
        }
        return col;
      });
    }
  }, 'music_ripple', 'Ripple', 'Music', ['color1', 'color2', 'rainbow', 'speed', 'reverse', ...MUSIC],
  'Every beat sends a wave of light rolling across all fans, over a glow that follows the treble.');

  // ---- interactive --------------------------------------------------------------------
  def(class extends Effect {
    reset() { this.fly = null; this.score = this.miss = 0; this.seen = null; this.caught_at = this.miss_at = -9; this.hover = 0; }
    render(c, leds) {
      const um = c.um, inp = c.inp, t = now();
      if (!this.fly) this.fly = new Fly(um, 0);
      const net = inp.inside ? um.nearestXY(inp.vx, inp.vy) : null;
      const sf = 0.4 + c.p.speed / 50;
      this.hover = net !== null && net === this.fly.unit ? this.hover + c.dt : 0;
      if (this.hover > 1.2 && this.fly.state === 'fly') { this.fly.state = 'out'; this.hover = 0; }
      this.fly.step(um, c.dt, sf, 0.6);
      if (this.fly.alpha <= 0.05 && this.fly.state === 'in' && this.fly.unit === net) this.fly.jump(um, net);
      if (this.seen === null) this.seen = inp.clicks;
      if (inp.clicks !== this.seen) {
        this.seen = inp.clicks;
        const at = inp.lastClickUnit !== null ? inp.lastClickUnit : net;
        if (at === this.fly.unit && this.fly.alpha > 0.4) {
          this.score += 1; this.caught_at = t; this.fly.jump(um, at);
          announce(`Caught! Score ${this.score}.`);
        } else { this.miss += 1; this.miss_at = t; }
      }
      this.info = `Caught ${this.score} · Missed ${this.miss}` + (net !== null ? ` · net on ${um.names[net]}` : '');
      const out = leds.map(() => BLACK);
      const miss = t - this.miss_at < 0.35;
      if (net !== null) for (const i of um.leds_of[net]) out[i] = miss ? [0.6, 0, 0] : [0.09, 0.09, 0.1];
      const flick = 0.7 + 0.3 * Math.sin(c.t * 9);
      for (const i of um.leds_of[this.fly.unit]) {
        const k = blob(leds[i], this.fly.x) * this.fly.alpha * flick;
        if (k > 0) out[i] = maxc(out[i], scale(FIREFLY, k));
      }
      const age = t - this.caught_at;
      if (age < 1.5) {
        const k = Math.exp(-age * 2.2);
        leds.forEach((l, i) => { out[i] = maxc(out[i], scale(hsv(l.pos + age * 0.8), k)); });
      }
      return out;
    }
  }, 'firefly_catch', 'Catch the Firefly', 'Interactive', ['speed'],
  'A game. Your pointer is the net: whichever fixture it’s over glows dim white. When the firefly lands there, click to catch it. Hover too long and it flees!',
  { input: { pointer: true, click: true }, hint: 'Move over the rig to aim the net, then click (or tap) the fixture with the green firefly. Keyboard: arrows move the net, Space catches.' });

  def(class extends Effect {
    render(c, leds) {
      const inp = c.inp, cnt = inp.scroll, idle = now() - inp.scroll_at, fresh = Math.exp(-idle * 0.7);
      const step = Math.max(1, c.p.scroll_step) / 360;
      this.info = `Scroll position: ${cnt >= 0 ? '+' : ''}${cnt}`;
      return leds.map((l) => {
        if (l.ring <= 1) return scale(hsv(cnt * step), 0.35 + 0.65 * Math.exp(-idle * 1.5));
        const r = ringSize(l), i = Math.floor(l.local * r + 0.5) % r, d = mod(cnt - i, r);
        if (d === 0) return hsv(cnt * step);
        return scale(hsv((cnt - d) * step), Math.exp(-d * 0.45) * (0.25 + 0.75 * fresh));
      });
    }
  }, 'scroll_wheel', 'Scroll Wheel', 'Interactive', ['scroll_step'],
  'Every wheel notch moves the light one LED around each fan ring and turns the color one step around the color wheel, leaving a trail of every color it passed through. Scroll the other way to rewind.',
  { input: { wheel: true }, hint: 'Scroll your mouse wheel over the rig. The page won’t scroll while you’re over it. Touch or keyboard: use the ▲ ▼ buttons or the arrow keys.' });

  def(class extends Effect {
    reset(n) { this.b = new Float32Array(n); this.h = new Float32Array(n); this.seen = null; this.wpm = 0; }
    render(c, leds) {
      const inp = c.inp, n = leds.length;
      if (this.seen === null) this.seen = inp.keys;
      const kps = inp.typing_speed();
      this.wpm += (kps * 12 - this.wpm) * Math.min(1, c.dt * 3);
      const heat = clamp(this.wpm / 90), hue = 0.66 * (1 - heat);
      const fresh = Math.min(10, inp.keys - this.seen);
      this.seen = inp.keys;
      for (let s = 0; s < Math.max(0, fresh); s++) {
        for (let j = 0; j < 5; j++) {
          const i = Math.floor(Math.random() * n);
          this.b[i] = 1;
          this.h[i] = c.p.rainbow ? Math.random() : hue + rand(-0.04, 0.04);
        }
      }
      const d = Math.exp(-c.dt * 2.5);
      this.info = `${Math.round(this.wpm)} WPM`;
      return leds.map((l, i) => {
        this.b[i] *= d;
        let col = scale(hsv(this.h[i]), this.b[i]);
        if (l.kind === 'keyboard') col = maxc(col, scale(hsv(hue), 0.05 + 0.5 * heat));
        return col;
      });
    }
  }, 'typing_sparks', 'Typing Sparks', 'Interactive', ['rainbow'],
  'Every keypress throws sparks onto random LEDs across the whole rig. Type faster and the sparks get hotter: blue → green → yellow → red. Your keyboard glows with your speed.',
  { input: { keys: true }, hint: 'Click the rig, then type anything. Only the number of keypresses is counted, never which key. On a phone, tap the rig.' });

  def(class extends Effect {
    reset() { this.wpm = 0; this.best = 0; }
    render(c, leds) {
      const target = c.inp.typing_speed() * 12;
      this.wpm += (target - this.wpm) * Math.min(1, c.dt * 2);
      this.best = Math.max(this.wpm, this.best - c.dt * 2);
      const fill = clamp(this.wpm / 100), bestf = clamp(this.best / 100);
      this.info = `${Math.round(this.wpm)} WPM (best ${Math.round(this.best)})`;
      return leds.map((l) => {
        if (l.ring <= 1) return scale(hsv(0.33 * (1 - fill)), 0.1 + 0.9 * fill);
        if (bestf > 0.03 && Math.abs(l.local - bestf) < 0.5 / ringSize(l)) return WHITE;
        if (l.local < fill) return hsv(0.33 * (1 - l.local));
        return [0.02, 0.02, 0.03];
      });
    }
  }, 'typing_meter', 'Typing Speed Meter', 'Interactive', [],
  'Every fan ring becomes a speedometer for your typing (0 → 100 WPM): rings fill green → yellow → red, and a white marker remembers your best recent burst.',
  { input: { keys: true }, hint: 'Click the rig and type as fast as you can. Only keypress counts are used. On a phone, tap quickly.' });

  def(class extends Effect {
    reset() { this.x = 0.5; this.y = 0.5; this.seen = null; this.flash_at = -9; }
    render(c, leds) {
      const inp = c.inp;
      const px = inp.vx / VW, py = inp.vy / VH;
      this.x += (px - this.x) * Math.min(1, c.dt * 10);
      this.y += (py - this.y) * Math.min(1, c.dt * 10);
      if (this.seen === null) this.seen = inp.clicks;
      if (inp.clicks !== this.seen) { this.seen = inp.clicks; this.flash_at = now(); }
      const fl = Math.exp(-(now() - this.flash_at) * 5);
      const col = lerp(hsv(this.y), WHITE, fl), bg = scale(c.c2, 0.05);
      const sy = this.y * VH;
      return leds.map((l) => {
        const d = Math.hypot(l.x / VW - this.x, (l.y - sy) / VW);
        return lerp(bg, col, gauss(d / 0.11));
      });
    }
  }, 'mouse_spotlight', 'Mouse Spotlight', 'Interactive', ['color2'],
  'A spotlight follows your mouse. In the app, left↔right slides it across your fans and up↕down changes its color. Click to make it flash white. Color 2 is the background glow.',
  { input: { pointer: true, click: true }, hint: 'Move over the rig: the spotlight follows you and its height picks the color. Click to flash white. Keyboard: arrow keys.' });

  def(class extends Effect {
    reset() { this.prev = null; this.energy = 0; this.ph = 0; }
    render(c, leds) {
      const px = c.inp.vx / VW, py = c.inp.vy / VH;
      if (this.prev && c.dt > 0) {
        const sp = Math.hypot(px - this.prev[0], py - this.prev[1]) / c.dt;
        this.energy = clamp(this.energy * Math.exp(-c.dt * 0.7) + sp * c.dt * 0.5);
      }
      this.prev = [px, py];
      const e = this.energy;
      this.ph += c.dt * (0.05 + e * 2.5);
      const calm = scale(c.c1, 0.2 + 0.15 * Math.sin(c.t * 1.2));
      this.info = `Energy ${Math.round(e * 100)}%`;
      return leds.map((l) => lerp(calm, hsv(l.pos * 1.5 + l.local * 0.3 - this.ph), e));
    }
  }, 'mouse_energy', 'Mouse Energy', 'Interactive', ['color1'],
  'Shake your mouse to charge the rig! Fast movement builds energy into a bright, racing rainbow storm. Stop moving and it calms down to a slow Color 1 breathe.',
  { input: { pointer: true }, hint: 'Shake your pointer back and forth over the rig to charge it up.' });

  def(class extends Effect {
    reset() { this.seen = null; this.bursts = []; }
    render(c, leds) {
      const um = c.um, inp = c.inp, t = now();
      if (this.seen === null) this.seen = inp.clicks;
      const fresh = Math.min(5, inp.clicks - this.seen);
      for (let k = 0; k < fresh; k++) {
        const q = inp.clickQueue.shift();
        const u = q ? q.unit : choice(um.units);
        const col = c.p.rainbow ? hsv(Math.random()) : q && q.button === 3 ? c.c2 : c.c1;
        this.bursts.push([t, um.pos[u], u, col]);
      }
      this.seen = inp.clicks;
      this.bursts = this.bursts.filter((b) => t - b[0] < 2.5);
      const out = leds.map(() => BLACK);
      for (const [t0, pos, u, col] of this.bursts) {
        const age = t - t0, r = age * 0.45;
        leds.forEach((l, i) => {
          let k = gauss((Math.abs(l.pos - pos) - r) / 0.04) * Math.exp(-age * 1.6);
          if (l.unit === u) k = Math.max(k, Math.exp(-age * 2.5) * (0.6 + 0.4 * Math.sin(l.local * 18.8 + age * 25)));
          if (age < 1.5 && Math.random() < 0.015) k = Math.max(k, 0.7 * Math.exp(-age));
          if (k > 0.01) out[i] = maxc(out[i], scale(col, k));
        });
      }
      return out;
    }
  }, 'click_fireworks', 'Click Fireworks', 'Interactive', ['color1', 'color2', 'rainbow'],
  'Every mouse click launches a firework that bursts on a fan, then a shockwave rolls across the neighbouring fans. Left click = Color 1, right click = Color 2. Rainbow: random colors.',
  { input: { pointer: true, click: true }, hint: 'Click any fan to launch a firework there (in the app it lands on a random fan). Right-click for Color 2. Keyboard: Space.' });

  const PRESENCE_SCALE = 0.2; // the app waits 30 s; the demo is 5x quicker
  def(class extends Effect {
    reset() { this.last = null; this.move_at = now(); this.wake_at = -9; this.was_idle = 0; }
    render(c, leds) {
      const inp = c.inp, t = now(), ptr = `${inp.vx},${inp.vy}`;
      if (this.last !== null && ptr !== this.last) this.move_at = t;
      this.last = ptr;
      const idle = (t - Math.max(inp.key_at, inp.click_at, inp.scroll_at, this.move_at)) / PRESENCE_SCALE;
      if (this.was_idle > 20 && idle < 0.5 / PRESENCE_SCALE) this.wake_at = t;
      this.was_idle = idle;
      const sleep = clamp((idle - 30) / 60);
      const sleepy_b = 0.04 + (0.12 * (1 - Math.cos(c.t * 0.8))) / 2;
      const age = t - this.wake_at;
      this.info = idle < 30 ? 'You’re here' : `Away for ${Math.round(idle * PRESENCE_SCALE)} s`;
      return leds.map((l) => {
        const awake = scale(c.c1, 0.45 + 0.55 * (0.5 + 0.5 * Math.sin(l.pos * 6.28 - c.t * 0.6)));
        let col = lerp(awake, scale(c.c2, sleepy_b), sleep);
        if (age < 1.8) col = addc(col, scale(WHITE, gauss((l.pos - age * 0.8) / 0.08)));
        return col;
      });
    }
  }, 'presence', 'Presence', 'Interactive', ['color1', 'color2'],
  'The lights know when you’re there. While you work: a calm, flowing Color 1. Walk away and after 30 s they slowly fall asleep into a gentle Color 2 breathe. Come back and a bright wave greets you.',
  { input: { pointer: true, click: true, keys: true, wheel: false }, hint: 'Leave the rig alone for 6 seconds (30 s in the app) and watch it fall asleep, then move over it again for a wake-up wave.' });

  def(class extends Effect {
    reset() { this.x = 0; this.dir = 1; this.seen_c = this.seen_s = null; this.hue = null; this.bounce_at = -9; this.bounce_end = 0; }
    render(c, leds) {
      const um = c.um, inp = c.inp;
      if (this.seen_c === null) { this.seen_c = inp.clicks; this.seen_s = inp.scroll; }
      if (inp.clicks !== this.seen_c) { this.seen_c = inp.clicks; this.hue = Math.random(); }
      const boost = clamp(inp.scroll - this.seen_s, -6, 10), steps = um.steps.length;
      const v = (6 + c.p.speed * 0.5) * Math.pow(1.2, boost);
      this.x += this.dir * v * c.dt;
      const t = now();
      if (this.x >= steps - 1 || this.x <= 0) {
        this.bounce_end = this.x <= 0 ? 0 : 1;
        this.x = clamp(this.x, 0, steps - 1);
        this.dir = -this.dir;
        this.bounce_at = t;
      }
      const col = this.hue !== null ? hsv(this.hue) : c.c1;
      const out = leds.map(() => BLACK);
      for (let s = Math.max(0, Math.floor(this.x) - 2); s < Math.min(steps, Math.floor(this.x) + 3); s++) {
        const k = Math.max(0, 1 - Math.abs(s - this.x) / 1.6);
        for (const i of um.steps[s]) out[i] = maxc(out[i], scale(col, k));
      }
      const fl = Math.exp(-(t - this.bounce_at) * 6);
      if (fl > 0.02) {
        const end = this.bounce_end === 0 ? um.steps.slice(0, 3) : um.steps.slice(-3);
        for (const st of end) for (const i of st) out[i] = maxc(out[i], [fl, fl, fl]);
      }
      this.info = `Speed ×${Math.pow(1.2, boost).toFixed(1)} (scroll to change)`;
      return out;
    }
  }, 'scroll_pong', 'Scroll Pong', 'Interactive', ['color1', 'speed'],
  'A small ball of 2–3 LEDs bounces end to end through every fan, the GPU, mouse and keyboard. Scroll up to speed it up, down to slow it down, click to change its color.',
  { input: { wheel: true, click: true, pointer: true }, hint: 'Scroll over the rig to change the ball’s speed; click to change its color. Touch or keyboard: ▲ ▼ buttons, arrow keys, Space.' });

  def(class extends Effect {
    reset() { this.head = 0; this.length = 4; this.seen = null; this.eat_at = -9; this.food = null; }
    placeFood(um) {
      const steps = um.steps.length, h = Math.floor(this.head), body = new Set();
      for (let k = 0; k < this.length; k++) body.add(mod(h - k, steps));
      const free = [];
      for (let s = 0; s < steps; s++) if (!body.has(s)) free.push(s);
      this.food = free.length ? choice(free) : 0;
    }
    render(c, leds) {
      const um = c.um, inp = c.inp, steps = um.steps.length;
      if (this.food === null) this.placeFood(um);
      if (this.seen === null) this.seen = inp.scroll;
      const jump = inp.scroll - this.seen;
      this.seen = inp.scroll;
      this.head = mod(this.head + (3 + c.p.speed / 6) * c.dt + jump * 2, steps);
      const h = Math.floor(this.head), t = now();
      if (h === this.food) {
        this.length += 2; this.eat_at = t;
        if (this.length > 40) this.length = 4;
        this.placeFood(um);
      }
      let out = leds.map(() => BLACK);
      const blink = 0.4 + 0.6 * (0.5 + 0.5 * Math.sin(c.t * 10));
      for (const i of um.steps[this.food]) out[i] = scale(c.c2, blink);
      for (let k = 0; k < this.length; k++) {
        const s = mod(h - k, steps), col = k === 0 ? WHITE : scale(c.c1, 1 - (0.8 * k) / this.length);
        for (const i of um.steps[s]) out[i] = col;
      }
      const fl = Math.exp(-(t - this.eat_at) * 4);
      if (fl > 0.05) out = out.map((col) => addc(col, scale(c.c2, 0.4 * fl)));
      this.info = `Length ${this.length}`;
      return out;
    }
  }, 'snake', 'Snake', 'Interactive', ['color1', 'color2', 'speed'],
  'A snake slithers LED by LED through every fan, the GPU, mouse and keyboard, hunting its food (blinking Color 2). Every bite makes it longer. Scroll to boost it forward (or backward).',
  { input: { wheel: true }, hint: 'Scroll over the rig to boost the snake forward or backward toward its food. Touch or keyboard: ▲ ▼ buttons or arrow keys.' });

  // ---- system -------------------------------------------------------------------------
  def(class extends Effect {
    reset() { this.v = { cpu: 0, gpu: 0, ram: 0 }; }
    render(c, leds) {
      for (const k of ['cpu', 'gpu', 'ram']) this.v[k] += (c.sys[k] - this.v[k]) * Math.min(1, c.dt * 3);
      this.info = `CPU ${Math.round(this.v.cpu * 100)}%  GPU ${Math.round(this.v.gpu * 100)}%  RAM ${Math.round(this.v.ram * 100)}%`;
      return leds.map((l) => {
        const v = this.v[l.kind === 'gpu' ? 'gpu' : l.kind === 'keyboard' || l.kind === 'mouse' ? 'ram' : 'cpu'];
        if (l.ring <= 1) return scale(hsv(0.33 * (1 - v)), 0.25 + 0.75 * v);
        if (l.local <= Math.max(v, 0.5 / ringSize(l))) return hsv(0.33 * (1 - l.local));
        return [0.015, 0.015, 0.02];
      });
    }
  }, 'system_monitor', 'System Monitor', 'System', ['cpu_load'],
  'Your fans become live gauges. Case fans + board = CPU load (each ring fills up), GPU fans = GPU load, keyboard + mouse = RAM use. Green → yellow → red as the load rises.',
  { hint: 'Drag “Simulated CPU load” in the panel. The app reads your real CPU, GPU and RAM.' });

  def(class extends Effect {
    reset() { this.ph = 0; this.bpm = 60; }
    render(c, leds) {
      this.bpm += (50 + c.sys.cpu * 110 - this.bpm) * Math.min(1, c.dt);
      this.ph += (c.dt * this.bpm) / 60;
      this.info = `${Math.round(this.bpm)} BPM`;
      return leds.map((l) => {
        const x = mod(this.ph - l.pos * 0.06, 1);
        const p = gauss(x / 0.045) + gauss((x - 1) / 0.045) + 0.6 * gauss((x - 0.17) / 0.05);
        return scale(c.c1, 0.06 + 0.94 * Math.min(1, p));
      });
    }
  }, 'heartbeat', 'Heartbeat', 'System', ['color1', 'cpu_load'],
  'A lub-dub heartbeat through every light. It beats faster the harder your CPU works (50 → 160 BPM).',
  { hint: 'Drag “Simulated CPU load” and listen with your eyes: the heart rate follows it.' });

  def(class extends Effect {
    render(c, leds) {
      const x = clamp((c.p.temp - 35) / 50), col = hsv(0.66 * (1 - x));
      const b = 0.85 + 0.15 * Math.sin(c.t * (1.5 + 4 * x));
      this.info = `${Math.round(c.p.temp)} °C`;
      const out = scale(col, b);
      return leds.map(() => out);
    }
  }, 'temperature', 'Temperature', 'System', ['temp'],
  'Blue when cool, through green and yellow, to red when hot (35 °C → 85 °C).',
  { hint: 'Drag “Simulated temperature”. The app reads your CPU or GPU sensor.' });

  // ---- tools --------------------------------------------------------------------------
  const TEST = [[1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 1, 0], [1, 0, 1], [0, 1, 1], [1, 1, 1], [1, 0.4, 0]];
  def(class extends Effect { render(c, leds) { return leds.map((l) => TEST[l.unit % TEST.length]); } },
    'fan_test', 'Fan Map Test', 'Tools', [],
    'Each fan should be fully lit in ONE color: red, green, blue, yellow… In the app, if a fan shows two colors, lower “LEDs per case fan”; if part of the last fan on a header is dark, raise it.');
  def(class extends Effect { render(c, leds) { return leds.map(() => BLACK); } }, 'off', 'Off', 'Tools', [], 'All lights off.');

  const CATS = [
    ['Interactive', ['firefly_catch', 'scroll_wheel', 'typing_sparks', 'typing_meter', 'mouse_spotlight', 'mouse_energy', 'click_fireworks', 'presence', 'scroll_pong', 'snake']],
    ['Music', ['music_beat', 'music_spectrum', 'music_ripple', 'music']],
    ['Ambient', ['firefly', 'fire', 'twinkle', 'raindrops', 'lightning', 'aurora', 'meteors']],
    ['Fan Rings', ['spin', 'rainbow_ring', 'marquee']],
    ['Classic', ['static', 'breathing', 'color_cycle', 'rainbow_wave', 'gradient', 'comet', 'strobe', 'police']],
    ['System', ['system_monitor', 'heartbeat', 'temperature']],
    ['Tools', ['fan_test', 'off']],
  ];
  const isMusic = (key) => key.startsWith('music');

  // ======================================================================================
  // audio: a silent simulated signal, and a live analyser (port of sensors.Audio)
  // ======================================================================================
  const NB = 16;
  const newAudioState = () => ({ level: 0, bass: 0, mid: 0, treble: 0, bands: new Array(NB).fill(0), beats: 0 });
  const smooth = (cfg) => { const down = 0.5 - ((cfg.smoothing ?? 50) / 100) * 0.45; return (o, n, up = 0.7) => o + (n - o) * (n > o ? up : down); };
  const gainOf = (cfg, key) => Math.pow(2, ((cfg[key] ?? 50) - 50) / 25);

  // A 122 BPM pattern (kick, snare, hats, arp, bassline) rendered straight into analysis numbers.
  class SimSignal {
    constructor() { this.t = 0; this.lastBeat = -1; }
    update(st, dt, cfg) {
      this.t += dt;
      const spb = 60 / 122, tb = this.t / spb, bi = Math.floor(tb), since = (tb - bi) * spb;
      const brk = Math.floor(bi / 4) % 8 === 7;
      const kick = brk ? 0 : Math.exp(-since * 9);
      const snare = bi % 2 === 1 ? Math.exp(-since * 7) : 0;
      const s16 = tb * 4, i16 = Math.floor(s16), since16 = (s16 - i16) * spb / 4;
      const hat = Math.exp(-since16 * 30) * (i16 % 2 ? 1 : 0.55);
      const arpN = [0, 2, 4, 2, 5, 3, 1, 4][i16 % 8], arpEnv = Math.exp(-since16 * 9);
      const pad = brk ? 0.5 + 0.25 * Math.sin(this.t * 2) : 0.2;
      const bassline = 0.55 * (1 - 0.8 * kick);
      const g = (0.4 + ((cfg.sensitivity ?? 50) / 100) * 1.6) / 1.2, bg = gainOf(cfg, 'bass_gain');
      const sm = smooth(cfg);
      let mid = 0, tre = 0;
      for (let i = 0; i < NB; i++) {
        let v;
        if (i < 3) v = kick * (1 - i * 0.12) + bassline * 0.35 * (i / 3);
        else if (i < 6) v = bassline * (0.75 - (i - 3) * 0.12) + (kick * 0.35 * (6 - i)) / 3;
        else if (i < 11) v = pad * 0.6 + snare * 0.75 + arpEnv * gauss((i - (6 + arpN * 0.9)) / 1.1) * 0.9;
        else v = hat * (0.75 + 0.25 * Math.random()) * (0.6 + (i - 11) * 0.1) + snare * 0.45;
        v = clamp(v * (i < 4 ? bg : 1) * g * (0.92 + 0.16 * Math.random()));
        st.bands[i] = sm(st.bands[i], v);
        if (i >= 5 && i < 11) mid += st.bands[i] / 6;
        if (i >= 11) tre += st.bands[i] / 5;
      }
      st.bass = sm(st.bass, clamp((kick + bassline * 0.25) * bg * g), 0.85);
      st.mid = mid;
      st.treble = tre;
      st.level = sm(st.level, clamp((0.25 + kick * 0.45 + snare * 0.2 + hat * 0.08 + pad * 0.2) * g));
      if (bi !== this.lastBeat) { this.lastBeat = bi; if (!brk) st.beats++; }
    }
  }

  class LiveAnalyzer {
    constructor(actx, input) {
      const an = actx.createAnalyser();
      an.fftSize = 2048;
      an.smoothingTimeConstant = 0;
      input.connect(an);
      this.an = an;
      this.db = new Float32Array(an.frequencyBinCount);
      this.td = new Float32Array(an.fftSize);
      this.spec = new Float32Array(an.frequencyBinCount);
      const sr = actx.sampleRate, N = an.fftSize;
      this.freqs = Float32Array.from({ length: N / 2 }, (_, i) => (i * sr) / N);
      const edges = [];
      for (let i = 0; i <= NB; i++) edges.push(35 * Math.pow(10000 / 35, i / NB));
      this.bandIdx = [];
      for (let b = 0; b < NB; b++) {
        const lo = edges[b], hi = edges[b + 1], ix = [];
        this.freqs.forEach((f, i) => { if (f >= lo && f < hi) ix.push(i); });
        if (!ix.length) {
          let best = 0;
          this.freqs.forEach((f, i) => { if (Math.abs(f - lo) < Math.abs(this.freqs[best] - lo)) best = i; });
          ix.push(best);
        }
        this.bandIdx.push(ix);
      }
      this.ceil = { level: 1e-3, bass: 1e-3, mid: 1e-3, treble: 1e-3 };
      this.bandCeil = new Float32Array(NB).fill(1e-3);
      this.hist = [];
      this.cutoff = null;
      this.beat_at = 0;
    }
    range(lo, hi) {
      let a = 0, b = 0;
      while (a < this.freqs.length && this.freqs[a] < lo) a++;
      b = a;
      while (b < this.freqs.length && this.freqs[b] < hi) b++;
      return [a, b];
    }
    update(st, cfg) {
      this.an.getFloatFrequencyData(this.db);
      this.an.getFloatTimeDomainData(this.td);
      const spec = this.spec;
      for (let i = 0; i < spec.length; i++) spec[i] = Number.isFinite(this.db[i]) ? Math.pow(10, this.db[i] / 20) : 0;
      const want = cfg.bass_cutoff ?? 160;
      if (want !== this.cutoff) {
        this.cutoff = want;
        this.groups = { bass: this.range(25, want), mid: this.range(want, 2000), treble: this.range(2000, 10000) };
      }
      const g = 0.4 + ((cfg.sensitivity ?? 50) / 100) * 1.6;
      let ss = 0;
      for (let i = this.td.length - 512; i < this.td.length; i++) ss += this.td[i] * this.td[i];
      const rms = Math.sqrt(ss / 512);
      const gate = Math.pow((cfg.noise_gate ?? 10) / 100, 2) * 0.05, silent = rms < gate;
      const vals = { level: rms };
      for (const k of ['bass', 'mid', 'treble']) {
        const [a, b] = this.groups[k];
        let s = 0;
        for (let i = a; i < b; i++) s += spec[i];
        vals[k] = b > a ? s / (b - a) : 0;
      }
      const gains = { level: g, bass: g * gainOf(cfg, 'bass_gain'), mid: g * gainOf(cfg, 'mid_gain'), treble: g * gainOf(cfg, 'treble_gain') };
      const out = {};
      for (const k of Object.keys(vals)) {
        const v = vals[k];
        this.ceil[k] = Math.max(v, this.ceil[k] * 0.9985, 1e-4);
        out[k] = silent || v < this.ceil[k] * 0.02 ? 0 : Math.min(1, (v / this.ceil[k]) * gains[k]);
      }
      const sm = smooth(cfg);
      for (let b = 0; b < NB; b++) {
        const ix = this.bandIdx[b];
        let s = 0;
        for (const i of ix) s += spec[i];
        const v = s / ix.length;
        this.bandCeil[b] = Math.max(v, this.bandCeil[b] * 0.998);
        let n = clamp((v / Math.max(this.bandCeil[b], 1e-4)) * g);
        if (v < this.bandCeil[b] * 0.03 || silent) n = 0;
        st.bands[b] = sm(st.bands[b], n);
      }
      st.level = sm(st.level, out.level);
      st.bass = sm(st.bass, out.bass, 0.85);
      st.mid = sm(st.mid, out.mid);
      st.treble = sm(st.treble, out.treble);
      // Beat: bass energy well above its average over the last second.
      const e = vals.bass;
      this.hist.push(e);
      if (this.hist.length > 60) this.hist.shift();
      const avg = this.hist.reduce((s, x) => s + x, 0) / this.hist.length;
      const ratio = 1.15 + (cfg.beat_threshold ?? 30) / 100, gap = (cfg.beat_gap ?? 220) / 1000, t = now();
      if (!silent && this.hist.length > 10 && e > avg * ratio && out.bass > 0.3 && t - this.beat_at > gap) {
        st.beats++;
        this.beat_at = t;
      }
    }
  }

  // A little techno loop synthesised live with WebAudio (no audio files).
  class SynthBeat {
    constructor(actx, out) {
      this.actx = actx;
      this.out = actx.createGain();
      this.out.gain.value = 0.5;
      this.out.connect(out);
      const len = actx.sampleRate;
      this.noise = actx.createBuffer(1, len, actx.sampleRate);
      const d = this.noise.getChannelData(0);
      for (let i = 0; i < len; i++) d[i] = Math.random() * 2 - 1;
      this.timer = null;
    }
    start() {
      if (this.timer) return;
      this.step = 0;
      this.next = this.actx.currentTime + 0.08;
      this.timer = setInterval(() => this.tick(), 25);
      this.tick();
    }
    stop() { clearInterval(this.timer); this.timer = null; }
    tick() {
      const s16 = 60 / 122 / 4;
      while (this.next < this.actx.currentTime + 0.15) { this.play(this.step, this.next, s16); this.next += s16; this.step++; }
    }
    env(g, t, peak, a, d) {
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(peak, t + a);
      g.gain.exponentialRampToValueAtTime(0.0001, t + a + d);
    }
    voice(type, freq, t, peak, a, d, filter) {
      const ac = this.actx, o = ac.createOscillator(), g = ac.createGain();
      o.type = type;
      o.frequency.setValueAtTime(freq, t);
      let node = o;
      if (filter) { const f = ac.createBiquadFilter(); Object.assign(f, { type: filter.type }); f.frequency.value = filter.f; f.Q.value = filter.q || 1; o.connect(f); node = f; }
      node.connect(g); g.connect(this.out);
      this.env(g, t, peak, a, d);
      o.start(t); o.stop(t + a + d + 0.05);
      return o;
    }
    noiseHit(t, type, f, peak, d, q = 1) {
      const ac = this.actx, s = ac.createBufferSource(), fl = ac.createBiquadFilter(), g = ac.createGain();
      s.buffer = this.noise;
      fl.type = type; fl.frequency.value = f; fl.Q.value = q;
      s.connect(fl); fl.connect(g); g.connect(this.out);
      this.env(g, t, peak, 0.002, d);
      s.start(t, Math.random() * 0.5); s.stop(t + d + 0.05);
    }
    play(step, t, s16) {
      const CH = [
        { root: 55, notes: [440, 523.25, 659.25] },
        { root: 43.65, notes: [349.23, 440, 523.25] },
        { root: 65.41, notes: [523.25, 659.25, 783.99] },
        { root: 49, notes: [392, 493.88, 587.33] },
      ];
      const s = step % 16, ch = CH[Math.floor(step / 16) % 4];
      if (s % 4 === 0) { // kick
        const o = this.voice('sine', 150, t, 0.95, 0.003, 0.42);
        o.frequency.exponentialRampToValueAtTime(42, t + 0.13);
      }
      if (s === 4 || s === 12) { this.noiseHit(t, 'bandpass', 1900, 0.5, 0.18, 0.7); this.voice('triangle', 190, t, 0.25, 0.002, 0.09); }
      if (s % 2 === 1) this.noiseHit(t, 'highpass', 7500, s === 15 ? 0.16 : 0.11, s === 15 ? 0.22 : 0.045);
      if (s % 2 === 0) this.voice('sawtooth', ch.root * (s % 8 === 6 ? 2 : 1), t, 0.2, 0.005, s16 * 1.6, { type: 'lowpass', f: 380, q: 7 });
      this.voice('square', ch.notes[[0, 1, 2, 1, 2, 0, 1, 2][s % 8]] * (s >= 8 ? 2 : 1), t, 0.045, 0.004, 0.16, { type: 'lowpass', f: 3200 });
      if (s === 0) ch.notes.forEach((f) => this.voice('triangle', f / 2, t, 0.03, 0.4, s16 * 14));
    }
  }

  // Shared playground audio: simulated by default; synth loop or a local file on request.
  const Music = {
    mode: 'sim', st: newAudioState(), sim: new SimSignal(), actx: null, master: null, live: null, synth: null, el: null, url: null,
    ensure() {
      if (!this.actx) {
        const AC = window.AudioContext || window.webkitAudioContext;
        if (!AC) return false;
        this.actx = new AC();
        this.master = this.actx.createGain();
        this.master.connect(this.actx.destination);
        this.live = new LiveAnalyzer(this.actx, this.master);
        this.synth = new SynthBeat(this.actx, this.master);
      }
      if (this.actx.state === 'suspended') this.actx.resume();
      return true;
    },
    stopAll() { if (this.synth) this.synth.stop(); if (this.el) this.el.pause(); },
    useSim() { this.stopAll(); this.mode = 'sim'; },
    useSynth() { if (!this.ensure()) return false; this.stopAll(); this.synth.start(); this.mode = 'live'; return true; },
    useFile(file) {
      if (!this.ensure()) return false;
      this.stopAll();
      if (this.url) URL.revokeObjectURL(this.url);
      this.url = URL.createObjectURL(file);
      const el = document.createElement('audio');
      el.src = this.url; el.loop = true;
      this.actx.createMediaElementSource(el).connect(this.master);
      this.el = el;
      this.mode = 'live';
      return el.play();
    },
    update(st, dt, cfg) { if (this.mode === 'sim') this.sim.update(st, dt, cfg); else this.live.update(st, cfg); },
  };

  // ======================================================================================
  // input (port of sensors.InputEvents, fed by events over the canvas)
  // ======================================================================================
  class Input {
    constructor() {
      this.scroll = 0; this.scroll_at = -99; this.clicks = 0; this.click_at = -99; this.keys = 0; this.key_at = -99;
      this.keyTimes = []; this.vx = VW / 2; this.vy = VH / 2; this.inside = false; this.lastClickUnit = null; this.clickQueue = [];
    }
    typing_speed() { const t = now(); this.keyTimes = this.keyTimes.filter((k) => t - k < 3); return this.keyTimes.length / 3; }
    key() { this.keys++; this.key_at = now(); this.keyTimes.push(this.key_at); }
    wheel(n) { this.scroll += n; this.scroll_at = now(); }
    click(unit, button = 1) {
      this.clicks++; this.click_at = now(); this.lastClickUnit = unit;
      this.clickQueue.push({ unit, button });
      if (this.clickQueue.length > 10) this.clickQueue.shift();
    }
  }

  // ======================================================================================
  // renderer: dark hardware painted once, LEDs + bloom painted every frame
  // ======================================================================================
  const LUT = new Uint8Array(1025);
  for (let i = 0; i <= 1024; i++) LUT[i] = Math.round(255 * Math.pow(i / 1024, 0.72));
  const q8 = (v) => (v <= 0 ? 0 : v >= 1 ? 255 : LUT[(v * 1024) | 0]);

  function rr(c, x, y, w, h, r) {
    c.beginPath();
    if (c.roundRect) c.roundRect(x, y, w, h, r);
    else {
      r = Math.min(r, w / 2, h / 2);
      c.moveTo(x + r, y); c.arcTo(x + w, y, x + w, y + h, r); c.arcTo(x + w, y + h, x, y + h, r);
      c.arcTo(x, y + h, x, y, r); c.arcTo(x, y, x + w, y, r); c.closePath();
    }
  }
  const lg = (c, x0, y0, x1, y1, stops) => { const g = c.createLinearGradient(x0, y0, x1, y1); stops.forEach(([o, col]) => g.addColorStop(o, col)); return g; };

  const BLADE = (() => {
    const P = (r, a) => [r * Math.cos(a), r * Math.sin(a)];
    const p = new Path2D();
    p.moveTo(...P(0.3, -0.12));
    p.quadraticCurveTo(...P(0.66, -0.1), ...P(0.94, 0.16));
    p.quadraticCurveTo(...P(0.99, 0.36), ...P(0.93, 0.56));
    p.quadraticCurveTo(...P(0.6, 0.46), ...P(0.3, 0.32));
    p.closePath();
    return p;
  })();

  class RigView {
    constructor(canvas, rig) {
      this.cv = canvas; this.g = canvas.getContext('2d'); this.rig = rig;
      this.bg = document.createElement('canvas'); this.fg = document.createElement('canvas');
      this.gA = document.createElement('canvas'); this.gB = document.createElement('canvas');
      this.hasFilter = typeof this.g.filter === 'string';
      this.blade = Math.random() * TAU;
      this.n = rig.leds.length;
      this.R = new Uint8Array(this.n); this.G = new Uint8Array(this.n); this.B = new Uint8Array(this.n);
      this.fans = rig.fixtures.map((f, u) => ({ f, u })).filter((o) => o.f.type === 'fan');
      if ('ResizeObserver' in window) new ResizeObserver(() => this.resize()).observe(canvas);
      else window.addEventListener('resize', () => this.resize());
      this.resize();
    }
    resize() {
      const w = this.cv.clientWidth;
      if (!w) return;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const W = Math.round(w * dpr), H = Math.round((W * VH) / VW);
      if (W === this.cv.width && H === this.cv.height) return;
      this.cv.width = this.bg.width = this.fg.width = W;
      this.cv.height = this.bg.height = this.fg.height = H;
      this.gA.width = Math.ceil(W / 4); this.gA.height = Math.ceil(H / 4);
      this.gB.width = Math.ceil(W / 12); this.gB.height = Math.ceil(H / 12);
      this.k = W / VW;
      this.paintStatic();
      if (this.onResize) this.onResize();
    }
    toVirtual(clientX, clientY) {
      const r = this.cv.getBoundingClientRect();
      return [((clientX - r.left) / r.width) * VW, ((clientY - r.top) / r.height) * VH];
    }

    paintStatic() {
      const k = this.k;
      // ---- back layer ----
      let c = this.bg.getContext('2d');
      c.setTransform(k, 0, 0, k, 0, 0);
      let gr = c.createRadialGradient(450, 260, 30, 450, 300, 640);
      gr.addColorStop(0, '#0e1117'); gr.addColorStop(1, '#040507');
      c.fillStyle = gr; c.fillRect(0, 0, VW, VH);
      c.fillStyle = lg(c, 0, 530, 0, VH, [[0, '#0c0e13'], [1, '#060709']]);
      c.fillRect(0, 530, VW, VH - 530);
      c.fillStyle = 'rgba(255,255,255,0.05)'; c.fillRect(0, 530, VW, 1);
      // case
      c.save(); c.shadowColor = 'rgba(0,0,0,0.7)'; c.shadowBlur = 40; c.shadowOffsetY = 18;
      rr(c, 100, 16, 700, 500, 26); c.fillStyle = lg(c, 100, 16, 800, 516, [[0, '#1c1f27'], [1, '#0f1116']]); c.fill(); c.restore();
      c.strokeStyle = 'rgba(255,255,255,0.08)'; c.lineWidth = 1.2; c.stroke();
      c.fillStyle = '#0b0c10'; rr(c, 140, 514, 74, 10, 4); c.fill(); rr(c, 686, 514, 74, 10, 4); c.fill();
      rr(c, GLASS.x, GLASS.y, GLASS.w, GLASS.h, 16); c.fillStyle = '#07080b'; c.fill();
      c.save(); rr(c, GLASS.x, GLASS.y, GLASS.w, GLASS.h, 16); c.clip();
      c.strokeStyle = 'rgba(255,255,255,0.018)'; c.lineWidth = 1;
      for (let x = GLASS.x + 20; x < GLASS.x + GLASS.w; x += 28) { c.beginPath(); c.moveTo(x, GLASS.y); c.lineTo(x, GLASS.y + GLASS.h); c.stroke(); }
      // motherboard
      rr(c, 296, 122, 398, 252, 8); c.fillStyle = '#0b0d12'; c.fill(); c.strokeStyle = 'rgba(255,255,255,0.05)'; c.stroke();
      c.strokeStyle = 'rgba(120,200,255,0.05)'; c.lineWidth = 1.2;
      for (let i = 0; i < 9; i++) { c.beginPath(); c.moveTo(310, 300 + i * 7); c.lineTo(400 + i * 10, 300 + i * 7); c.lineTo(420 + i * 10, 280 + i * 7); c.lineTo(540, 280 + i * 7); c.stroke(); }
      c.fillStyle = '#161920'; rr(c, 308, 132, 120, 24, 5); c.fill(); rr(c, 308, 132, 26, 130, 5); c.fill();
      c.fillStyle = 'rgba(255,255,255,0.035)';
      for (let i = 0; i < 8; i++) c.fillRect(314 + i * 14, 136, 8, 16);
      c.fillStyle = '#0e1015'; for (let i = 0; i < 2; i++) { rr(c, 330, 334 + i * 18, 330, 6, 3); c.fill(); }
      // AIO tubes from the pump to the top radiator
      c.lineCap = 'round';
      [[456, 444], [484, 566]].forEach(([x0, x1]) => {
        c.beginPath(); c.moveTo(x0, 200); c.bezierCurveTo(x0, 150, x1, 160, x1, 112);
        c.strokeStyle = '#0d0f13'; c.lineWidth = 11; c.stroke();
        c.strokeStyle = 'rgba(255,255,255,0.05)'; c.lineWidth = 2; c.stroke();
      });
      // CPU block
      c.beginPath(); c.arc(470, 228, 44, 0, TAU); c.fillStyle = lg(c, 430, 190, 510, 270, [[0, '#1b1e26'], [1, '#0d0f13']]); c.fill();
      c.strokeStyle = 'rgba(255,255,255,0.07)'; c.lineWidth = 1; c.stroke();
      c.beginPath(); c.arc(470, 228, 29, 0, TAU); c.strokeStyle = '#15171d'; c.lineWidth = 7; c.stroke();
      c.beginPath(); c.arc(470, 228, 21, 0, TAU); c.fillStyle = '#0a0b0e'; c.fill();
      c.beginPath(); c.arc(470, 228, 8, 0, TAU); c.strokeStyle = 'rgba(255,255,255,0.08)'; c.lineWidth = 2; c.stroke();
      // RAM
      const ram = this.rig.fixtures.find((f) => f.type === 'ram');
      for (let s = 0; s < ram.sticks; s++) {
        const x = ram.x0 + s * ram.pitch;
        rr(c, x - 6.5, ram.y0 - 4, 13, ram.y1 - ram.y0 + 8, 3); c.fillStyle = lg(c, x - 6, 0, x + 6, 0, [[0, '#1a1d24'], [1, '#101217']]); c.fill();
        rr(c, x - 3.5, ram.y0 + 6, 7, ram.y1 - ram.y0 - 12, 3); c.fillStyle = '#0d0e12'; c.fill();
      }
      // GPU
      c.save(); c.shadowColor = 'rgba(0,0,0,0.6)'; c.shadowBlur = 20; c.shadowOffsetY = 8;
      c.beginPath(); c.moveTo(316, 382); c.lineTo(776, 382); c.lineTo(786, 394); c.lineTo(786, 470); c.lineTo(306, 470); c.lineTo(296, 458); c.lineTo(296, 398); c.closePath();
      c.fillStyle = lg(c, 0, 382, 0, 470, [[0, '#1d2028'], [1, '#101217']]); c.fill(); c.restore();
      c.strokeStyle = 'rgba(255,255,255,0.08)'; c.lineWidth = 1; c.stroke();
      c.fillStyle = '#14161c'; c.fillRect(786, 376, 8, 100);
      c.strokeStyle = 'rgba(255,255,255,0.04)'; c.lineWidth = 2;
      c.beginPath(); c.moveTo(304, 400); c.lineTo(330, 386); c.moveTo(768, 466); c.lineTo(782, 452); c.stroke();
      // PSU shroud
      rr(c, GLASS.x, 480, GLASS.w, 24, 4); c.fillStyle = '#0d0f13'; c.fill();
      c.fillStyle = 'rgba(255,255,255,0.05)'; c.fillRect(GLASS.x, 480, GLASS.w, 1);
      c.fillStyle = 'rgba(255,255,255,0.13)'; c.font = '600 9px "JetBrains Mono", monospace'; c.textAlign = 'center'; c.textBaseline = 'middle';
      c.fillText('R G B   C O N T R O L', 450, 493);
      c.restore();
      // fans: frames, holes and the dark diffuser track
      for (const { f } of this.fans) {
        if (f.frame) {
          const h = f.frame / 2;
          rr(c, f.cx - h, f.cy - h, f.frame, f.frame, 10); c.fillStyle = lg(c, f.cx - h, f.cy - h, f.cx + h, f.cy + h, [[0, '#15171d'], [1, '#0c0d11']]); c.fill();
          c.strokeStyle = 'rgba(255,255,255,0.07)'; c.lineWidth = 1; c.stroke();
          c.fillStyle = '#050608';
          for (const [sx, sy] of [[-1, -1], [1, -1], [-1, 1], [1, 1]]) { c.beginPath(); c.arc(f.cx + sx * (h - 8), f.cy + sy * (h - 8), 2.6, 0, TAU); c.fill(); }
        }
        c.beginPath(); c.arc(f.cx, f.cy, f.r * 1.13, 0, TAU); c.fillStyle = '#040506'; c.fill();
        c.beginPath(); c.arc(f.cx, f.cy, f.r, 0, TAU); c.strokeStyle = '#17191f'; c.lineWidth = f.r * 0.2; c.stroke();
      }
      // keyboard
      const kb = this.rig.fixtures.find((f) => f.type === 'keyboard');
      c.save(); c.shadowColor = 'rgba(0,0,0,0.7)'; c.shadowBlur = 24; c.shadowOffsetY = 10;
      rr(c, kb.x0 - 12, kb.y0 - 11, kb.w + 24, kb.h + 22, 12); c.fillStyle = lg(c, 0, kb.y0, 0, kb.y0 + kb.h, [[0, '#17191f'], [1, '#0d0f13']]); c.fill(); c.restore();
      c.strokeStyle = 'rgba(255,255,255,0.08)'; c.lineWidth = 1; c.stroke();
      rr(c, kb.x0 - 3, kb.y0 - 2, kb.w + 6, kb.h + 4, 6); c.fillStyle = '#08090c'; c.fill();
      for (const l of this.rig.leds) {
        if (l.d.t !== 'key') continue;
        const d = l.d;
        rr(c, d.x, d.y, d.w, d.h, 3); c.fillStyle = '#15171c'; c.fill();
        c.fillStyle = 'rgba(255,255,255,0.045)'; c.fillRect(d.x + 2, d.y + 1, d.w - 4, 1);
      }
      // mouse
      const ms = this.rig.fixtures.find((f) => f.type === 'mouse');
      c.save(); c.shadowColor = 'rgba(0,0,0,0.7)'; c.shadowBlur = 20; c.shadowOffsetY = 8;
      rr(c, ms.cx - 28, ms.cy - 50, 56, 100, 27); c.fillStyle = lg(c, ms.cx - 28, 0, ms.cx + 28, 0, [[0, '#1a1c23'], [1, '#0e1014']]); c.fill(); c.restore();
      c.strokeStyle = 'rgba(255,255,255,0.08)'; c.lineWidth = 1; c.stroke();
      c.beginPath(); c.moveTo(ms.cx, ms.cy - 49); c.lineTo(ms.cx, ms.cy - 20); c.strokeStyle = 'rgba(0,0,0,0.6)'; c.lineWidth = 1.5; c.stroke();
      rr(c, ms.cx - 4.5, ms.cy - 46, 9, 19, 4); c.fillStyle = '#08090b'; c.fill();

      // ---- front layer: glass reflections + vignette ----
      c = this.fg.getContext('2d');
      c.setTransform(1, 0, 0, 1, 0, 0); c.clearRect(0, 0, this.fg.width, this.fg.height);
      c.setTransform(k, 0, 0, k, 0, 0);
      c.save(); rr(c, GLASS.x, GLASS.y, GLASS.w, GLASS.h, 16); c.clip();
      c.fillStyle = lg(c, 200, 0, 520, 520, [[0, 'rgba(255,255,255,0)'], [0.42, 'rgba(255,255,255,0)'], [0.5, 'rgba(255,255,255,0.035)'], [0.56, 'rgba(255,255,255,0.012)'], [0.6, 'rgba(255,255,255,0)'], [1, 'rgba(255,255,255,0)']]);
      c.fillRect(GLASS.x, GLASS.y, GLASS.w, GLASS.h);
      c.restore();
      rr(c, GLASS.x + 0.5, GLASS.y + 0.5, GLASS.w - 1, GLASS.h - 1, 16); c.strokeStyle = 'rgba(255,255,255,0.06)'; c.lineWidth = 1; c.stroke();
      gr = c.createRadialGradient(450, 320, 260, 450, 340, 640);
      gr.addColorStop(0, 'rgba(0,0,0,0)'); gr.addColorStop(1, 'rgba(0,0,0,0.5)');
      c.fillStyle = gr; c.fillRect(0, 0, VW, VH);
    }

    draw(cols, dt, spinning) {
      const g = this.g, k = this.k, leds = this.rig.leds, n = this.n, R = this.R, G = this.G, B = this.B;
      if (!k) return;
      for (let i = 0; i < n; i++) { const c = cols[i]; R[i] = q8(c[0]); G[i] = q8(c[1]); B[i] = q8(c[2]); }
      const W = this.cv.width, H = this.cv.height;
      g.setTransform(1, 0, 0, 1, 0, 0);
      g.globalCompositeOperation = 'source-over'; g.globalAlpha = 1;
      g.drawImage(this.bg, 0, 0);
      g.setTransform(k, 0, 0, k, 0, 0);

      // ambient light spilling into the case and onto the desk
      let ar = 0, ag = 0, ab = 0, an = 0, kr = 0, kg = 0, kbb = 0, kn = 0;
      for (let i = 0; i < n; i++) {
        const kind = leds[i].kind;
        if (kind === 'keyboard' || kind === 'mouse') { kr += R[i]; kg += G[i]; kbb += B[i]; kn++; }
        else { ar += R[i]; ag += G[i]; ab += B[i]; an++; }
      }
      ar /= an; ag /= an; ab /= an; kr /= kn; kg /= kn; kbb /= kn;
      g.globalCompositeOperation = 'lighter';
      let gr = g.createRadialGradient(450, 270, 20, 450, 270, 420);
      gr.addColorStop(0, `rgba(${ar | 0},${ag | 0},${ab | 0},0.16)`); gr.addColorStop(1, `rgba(${ar | 0},${ag | 0},${ab | 0},0)`);
      g.fillStyle = gr; g.fillRect(GLASS.x, GLASS.y, GLASS.w, GLASS.h);
      g.save(); g.translate(450, 534); g.scale(1, 0.12);
      gr = g.createRadialGradient(0, 0, 0, 0, 0, 420);
      gr.addColorStop(0, `rgba(${ar | 0},${ag | 0},${ab | 0},0.4)`); gr.addColorStop(1, `rgba(${ar | 0},${ag | 0},${ab | 0},0)`);
      g.fillStyle = gr; g.fillRect(-450, -420, 900, 840); g.restore();
      g.save(); g.translate(430, 618); g.scale(1, 0.3);
      gr = g.createRadialGradient(0, 0, 0, 0, 0, 360);
      gr.addColorStop(0, `rgba(${kr | 0},${kg | 0},${kbb | 0},0.22)`); gr.addColorStop(1, `rgba(${kr | 0},${kg | 0},${kbb | 0},0)`);
      g.fillStyle = gr; g.fillRect(-450, -400, 900, 800); g.restore();

      // fan blades, lit by their own ring
      g.globalCompositeOperation = 'source-over';
      if (spinning) this.blade += dt * 2.2;
      for (const { f, u } of this.fans) {
        let r = 0, gg = 0, b = 0, m = 0;
        for (let i = 0; i < n; i++) if (leds[i].unit === u) { r += R[i]; gg += G[i]; b += B[i]; m++; }
        r /= m; gg /= m; b /= m;
        const tint = (base, amt) => `rgb(${Math.min(255, base + r * amt) | 0},${Math.min(255, base + gg * amt) | 0},${Math.min(255, base + b * amt) | 0})`;
        g.save(); g.translate(f.cx, f.cy);
        const rb = f.r * 0.9;
        g.save(); g.scale(rb, rb);
        g.fillStyle = tint(18, 0.3);
        for (let j = 0; j < f.blades; j++) { g.save(); g.rotate(this.blade * f.spin + (j * TAU) / f.blades); g.fill(BLADE); g.restore(); }
        g.restore();
        g.beginPath(); g.arc(0, 0, f.r * 0.32, 0, TAU); g.fillStyle = tint(16, 0.42); g.fill();
        g.beginPath(); g.arc(0, 0, f.r * 0.2, 0, TAU); g.fillStyle = '#0a0b0e'; g.fill();
        g.restore();
      }

      // bloom: soft radial glows on a quarter-res buffer, blurred again at 1/12 res
      const a = this.gA.getContext('2d'), sA = this.gA.width / VW;
      a.setTransform(1, 0, 0, 1, 0, 0); a.globalCompositeOperation = 'source-over'; a.clearRect(0, 0, this.gA.width, this.gA.height);
      a.setTransform(sA, 0, 0, sA, 0, 0); a.globalCompositeOperation = 'lighter';
      for (let i = 0; i < n; i++) {
        const mx = Math.max(R[i], G[i], B[i]);
        if (mx < 6) continue;
        const l = leds[i], rgb = `${R[i]},${G[i]},${B[i]}`;
        const gg = a.createRadialGradient(l.x, l.y, 0, l.x, l.y, l.R);
        gg.addColorStop(0, `rgba(${rgb},${l.ga})`); gg.addColorStop(0.4, `rgba(${rgb},${l.ga * 0.38})`); gg.addColorStop(1, `rgba(${rgb},0)`);
        a.fillStyle = gg; a.fillRect(l.x - l.R, l.y - l.R, l.R * 2, l.R * 2);
      }
      const b = this.gB.getContext('2d');
      b.globalCompositeOperation = 'source-over'; b.clearRect(0, 0, this.gB.width, this.gB.height);
      if (this.hasFilter) b.filter = 'blur(1.5px)';
      b.drawImage(this.gA, 0, 0, this.gB.width, this.gB.height);
      if (this.hasFilter) b.filter = 'none';
      g.setTransform(1, 0, 0, 1, 0, 0); g.globalCompositeOperation = 'lighter';
      g.globalAlpha = 0.85; g.drawImage(this.gA, 0, 0, W, H);
      g.globalAlpha = 1; g.drawImage(this.gB, 0, 0, W, H);
      g.drawImage(this.gB, 0, 0, W, H);

      // LED bodies with a hot white-ish core
      g.setTransform(k, 0, 0, k, 0, 0); g.lineCap = 'butt';
      for (let i = 0; i < n; i++) {
        const r = R[i], gg2 = G[i], bb = B[i], mx = Math.max(r, gg2, bb);
        if (mx < 3) continue;
        const l = leds[i], d = l.d, I = mx / 255, w = 0.6 * I * I;
        const col = `rgb(${r},${gg2},${bb})`;
        const hot = `rgb(${(r + (255 - r) * w) | 0},${(gg2 + (255 - gg2) * w) | 0},${(bb + (255 - bb) * w) | 0})`;
        if (d.t === 'arc') {
          g.beginPath(); g.arc(d.cx, d.cy, d.r, d.a - d.span / 2, d.a + d.span / 2);
          g.strokeStyle = col; g.lineWidth = d.w; g.stroke();
          g.beginPath(); g.arc(d.cx, d.cy, d.r, d.a - d.span * 0.38, d.a + d.span * 0.38);
          g.strokeStyle = hot; g.lineWidth = d.w * 0.38; g.stroke();
        } else if (d.t === 'rect') {
          rr(g, d.x, d.y, d.w, d.h, 2); g.fillStyle = col; g.fill();
          g.fillStyle = hot; g.fillRect(d.x + d.w * 0.3, d.y + 1, d.w * 0.4, d.h - 2);
        } else if (d.t === 'dot') {
          g.beginPath(); g.arc(d.x, d.y, d.r, 0, TAU); g.fillStyle = col; g.fill();
          g.beginPath(); g.arc(d.x, d.y, d.r * 0.45, 0, TAU); g.fillStyle = hot; g.fill();
        } else if (d.t === 'key') {
          g.globalAlpha = 0.2; rr(g, d.x, d.y, d.w, d.h, 3); g.fillStyle = col; g.fill();
          g.globalAlpha = 1; g.fillStyle = hot;
          const lw = Math.min(d.w * 0.36, 9);
          g.fillRect(d.x + d.w / 2 - lw / 2, d.y + d.h / 2 - 1.4, lw, 2.8);
        }
      }
      g.setTransform(1, 0, 0, 1, 0, 0); g.globalCompositeOperation = 'source-over'; g.globalAlpha = 1;
      g.drawImage(this.fg, 0, 0);
    }
  }

  // ======================================================================================
  // runner: one clock per canvas, like engine.py
  // ======================================================================================
  const DEFAULTS = {
    color1: '#ff0040', color2: '#0080ff', speed: 40, brightness: 100, rainbow: false, reverse: false,
    firefly_count: 3, scroll_step: 15, sensitivity: 50, bass_gain: 50, beat_threshold: 30, smoothing: 50, music_floor: 4,
    cpu_load: 30, temp: 55,
  };
  const RUNNERS = [];

  class Runner {
    constructor(canvas, opts = {}) {
      this.rig = buildRig();
      this.um = new UnitMap(this.rig);
      this.view = new RigView(canvas, this.rig);
      this.view.onResize = () => { this.needsDraw = true; };
      this.p = Object.assign({}, DEFAULTS);
      this.inp = new Input();
      this.music = opts.music || null;
      this.sim = new SimSignal();
      this.audio = newAudioState();
      this.phase = 0; this.t = 0;
      this.playing = !reduced;
      this.visible = true;
      this.activeUntil = 0;
      this.needsDraw = true;
      this.fade = 1; this.prev = null;
      this.onFrame = null;
      if ('IntersectionObserver' in window) {
        new IntersectionObserver((es) => { this.visible = es[0].isIntersecting; }, { rootMargin: '80px' }).observe(canvas);
      }
      RUNNERS.push(this);
    }
    setEffect(key, { crossfade = false } = {}) {
      if (crossfade && this.effect) { this.prev = this.effect; this.fade = 0; } else { this.prev = null; this.fade = 1; }
      this.key = key;
      this.effect = new EFFECTS[key]();
      this.effect.reset(this.rig.leds.length);
      this.inp.clickQueue.length = 0;
      this.needsDraw = true;
    }
    wake(sec = 3) { this.activeUntil = Math.max(this.activeUntil, now() + sec); }
    frame(dt) {
      const p = this.p, leds = this.rig.leds;
      this.t += dt;
      const cpu = clamp(p.cpu_load / 100 + 0.05 * Math.sin(this.t * 1.3) + 0.03 * Math.sin(this.t * 3.7));
      const ctx = {
        phase: this.phase, t: this.t, dt, c1: hexToRgb(p.color1), c2: hexToRgb(p.color2), p, units: this.rig.units.length,
        lpf: LPF, inp: this.inp, audio: this.audio, um: this.um,
        sys: { cpu, gpu: clamp(cpu * 0.85 + 0.08 * Math.sin(this.t * 0.7)), ram: 0.42 + 0.05 * Math.sin(this.t * 0.3) },
      };
      if (isMusic(this.key) || (this.prev && isMusic(this.prev.constructor.key))) {
        if (this.music) this.music.update(this.audio, dt, p); else this.sim.update(this.audio, dt, p);
      }
      let cols = this.effect.render(ctx, leds);
      if (this.prev) {
        const old = this.prev.render(ctx, leds);
        this.fade = Math.min(1, this.fade + dt / 1.2);
        const f = this.fade * this.fade * (3 - 2 * this.fade);
        cols = cols.map((c, i) => lerp(old[i], c, f));
        if (this.fade >= 1) this.prev = null;
      }
      const br = clamp(p.brightness / 100);
      if (br < 1) cols = cols.map((c) => scale(c, br));
      this.view.draw(cols, dt, !reduced && (this.playing || now() < this.activeUntil));
      this.phase += dt * speedToRate(p.speed) * (p.reverse ? -1 : 1);
      if (this.onFrame) this.onFrame(dt);
    }
  }

  let last = performance.now();
  function loop(ts) {
    const dt = Math.min(0.1, Math.max(0, (ts - last) / 1000));
    last = ts;
    const t = now();
    for (const r of RUNNERS) {
      if (!r.visible || !r.effect) continue;
      const active = r.playing || t < r.activeUntil;
      if (active) { r.frame(dt); r.needsDraw = false; }
      else if (r.needsDraw) { r.frame(0); r.needsDraw = false; }
    }
    requestAnimationFrame(loop);
  }

  function bindPause(btn, runner) {
    const sync = () => {
      btn.setAttribute('aria-pressed', String(!runner.playing));
      btn.setAttribute('aria-label', runner.playing ? 'Pause animation' : 'Play animation');
    };
    btn.addEventListener('click', () => { runner.playing = !runner.playing; sync(); });
    sync();
    return sync;
  }

  // ======================================================================================
  // hero
  // ======================================================================================
  function initHero() {
    const canvas = document.getElementById('hero-canvas');
    if (!canvas) return;
    const r = new Runner(canvas);
    const SHOW = [
      ['rainbow_wave', { speed: 42 }],
      ['spin', { rainbow: true, speed: 55, color2: '#120024' }],
      ['music_beat', { rainbow: true }],
      ['aurora', { speed: 45 }],
      ['rainbow_ring', { speed: 38 }],
      ['music_spectrum', { rainbow: true }],
      ['firefly', { firefly_count: 6, speed: 50 }],
      ['meteors', { speed: 55, rainbow: true }],
      ['comet', { rainbow: true, speed: 52, color2: '#06142e' }],
    ];
    const DUR = 8;
    let idx = 0, held = 0;
    const nameEl = document.getElementById('hero-name'), bar = document.getElementById('hero-progress');
    const show = (i, fade) => {
      idx = mod(i, SHOW.length); held = 0;
      const [key, ov] = SHOW[idx];
      Object.assign(r.p, DEFAULTS, ov);
      r.setEffect(key, { crossfade: fade });
      const cls = EFFECTS[key];
      nameEl.textContent = cls.cat === 'Music' ? `Music: ${cls.label}` : cls.label;
    };
    show(0, false);
    r.onFrame = (dt) => {
      if (!r.playing) return;
      held += dt;
      if (bar) bar.style.width = `${Math.min(100, (held / DUR) * 100)}%`;
      if (held >= DUR) show(idx + 1, true);
    };
    document.getElementById('hero-next').addEventListener('click', () => { show(idx + 1, !reduced); r.wake(0.1); r.needsDraw = true; });
    bindPause(document.getElementById('hero-pause'), r);
  }

  // ======================================================================================
  // playground
  // ======================================================================================
  const CONTROL_DEFS = {
    speed: { label: 'Speed', min: 0, max: 100, fmt: (v) => `${v}` },
    brightness: { label: 'Brightness', min: 0, max: 100, fmt: (v) => `${v}%` },
    firefly_count: { label: 'Fireflies', min: 1, max: 12, fmt: (v) => `${v}` },
    scroll_step: { label: 'Color per notch', min: 3, max: 60, fmt: (v) => `${v}°` },
    sensitivity: { label: 'Sensitivity', min: 0, max: 100, fmt: (v) => `${v}` },
    bass_gain: { label: 'Bass boost', min: 0, max: 100, fmt: (v) => `×${Math.pow(2, (v - 50) / 25).toFixed(2)}` },
    beat_threshold: { label: 'Beat threshold', min: 0, max: 100, fmt: (v) => `${(1.15 + v / 100).toFixed(2)}×` },
    smoothing: { label: 'Smoothing', min: 0, max: 100, fmt: (v) => `${v}` },
    music_floor: { label: 'Min brightness', min: 0, max: 50, fmt: (v) => `${v}%` },
    cpu_load: { label: 'Simulated CPU load', min: 0, max: 100, fmt: (v) => `${v}%` },
    temp: { label: 'Simulated temperature', min: 30, max: 90, fmt: (v) => `${v} °C` },
  };

  function initPlayground() {
    const canvas = document.getElementById('pg-canvas');
    if (!canvas) return;
    const r = new Runner(canvas, { music: Music });
    const stage = document.getElementById('pg-stage');
    const $ = (id) => document.getElementById(id);
    const modesEl = $('pg-modes'), stylesEl = $('pg-styles'), controlsEl = $('pg-controls');
    const infoEl = $('pg-info'), hintEl = $('pg-hint'), wheelPad = $('pg-wheelpad');
    const musicEl = $('pg-music'), statusEl = $('pg-music-status'), fileEl = $('pg-file'), meterEl = $('pg-meter');
    let mode = 0;
    const lastInMode = CATS.map(([, keys]) => keys[0]);

    // meter bars
    const bars = [];
    for (let i = 0; i < NB; i++) { const b = document.createElement('i'); meterEl.appendChild(b); bars.push(b); }

    CATS.forEach(([name, keys], i) => {
      const b = document.createElement('button');
      b.type = 'button'; b.className = 'mode'; b.dataset.i = i;
      b.innerHTML = `<span>${name}</span><span class="n">${keys.length}</span>`;
      b.setAttribute('aria-label', `${name}, ${keys.length} styles`);
      b.addEventListener('click', () => selectMode(i));
      modesEl.appendChild(b);
    });

    function selectMode(i) {
      mode = i;
      [...modesEl.children].forEach((b, j) => b.setAttribute('aria-pressed', String(j === i)));
      stylesEl.innerHTML = '';
      CATS[i][1].forEach((key) => {
        const b = document.createElement('button');
        b.type = 'button'; b.className = 'chip'; b.dataset.key = key; b.textContent = EFFECTS[key].label;
        b.addEventListener('click', () => selectEffect(key));
        stylesEl.appendChild(b);
      });
      selectEffect(lastInMode[i]);
    }

    function selectEffect(key) {
      const cls = EFFECTS[key];
      lastInMode[mode] = key;
      [...stylesEl.children].forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.key === key)));
      if (!isMusic(key) && Music.mode !== 'sim') { Music.useSim(); syncMusicButtons('sim'); }
      r.setEffect(key);
      r.wake(1);
      $('pg-name').textContent = cls.cat === 'Music' ? `Music: ${cls.label}` : cls.label;
      $('pg-cat').textContent = cls.cat;
      $('pg-help').textContent = cls.help;
      const hint = cls.hint || (cls.cat === 'Music' ? 'Choose an audio source in the panel: a silent simulated beat, a live synth loop, or your own track.' : '');
      hintEl.innerHTML = hint ? `<span class="k">Try it</span><span></span>` : '';
      if (hint) hintEl.lastChild.textContent = hint;
      wheelPad.hidden = !(cls.input && cls.input.wheel);
      musicEl.hidden = cls.cat !== 'Music';
      infoEl.hidden = true;
      buildControls(cls);
      updateCli();
    }

    function slider(key, labelOverride) {
      const d = CONTROL_DEFS[key], id = `ctl-${key}`;
      const row = document.createElement('div');
      row.className = 'ctl-row';
      row.innerHTML = `<label for="${id}"></label><output for="${id}"></output><input type="range" id="${id}" min="${d.min}" max="${d.max}" step="1">`;
      row.querySelector('label').textContent = labelOverride || d.label;
      const inp = row.querySelector('input'), out = row.querySelector('output');
      const sync = () => {
        out.textContent = d.fmt(+inp.value);
        inp.style.setProperty('--p', `${((inp.value - d.min) / (d.max - d.min)) * 100}%`);
      };
      inp.value = r.p[key];
      sync();
      inp.addEventListener('input', () => { r.p[key] = +inp.value; sync(); r.wake(1.5); updateCli(); });
      return row;
    }
    function toggle(key, label) {
      const lab = document.createElement('label');
      lab.className = 'toggle';
      lab.innerHTML = '<input type="checkbox"><span class="sw" aria-hidden="true"></span><span></span>';
      lab.lastChild.textContent = label;
      const cb = lab.querySelector('input');
      cb.checked = !!r.p[key];
      cb.addEventListener('change', () => { r.p[key] = cb.checked; r.wake(1.5); updateCli(); });
      return lab;
    }
    function color(key, label) {
      const lab = document.createElement('label');
      lab.className = 'color-ctl';
      lab.innerHTML = '<input type="color"><span></span>';
      lab.lastChild.textContent = label;
      const ci = lab.querySelector('input');
      ci.value = r.p[key];
      ci.addEventListener('input', () => { r.p[key] = ci.value; r.wake(1.5); updateCli(); });
      return lab;
    }
    function group(title, kids) {
      const g = document.createElement('div');
      g.className = 'ctl-group';
      const t = document.createElement('p'); t.className = 'ctl-title'; t.textContent = title; g.appendChild(t);
      kids.forEach((k) => g.appendChild(k));
      return g;
    }

    function buildControls(cls) {
      const u = new Set(cls.uses);
      controlsEl.innerHTML = '';
      const cols = [];
      if (u.has('color1')) cols.push(color('color1', 'Color 1'));
      if (u.has('color2')) cols.push(color('color2', 'Color 2'));
      if (cols.length) { const w = document.createElement('div'); w.className = 'colors'; cols.forEach((c) => w.appendChild(c)); controlsEl.appendChild(w); }
      if (u.has('speed')) controlsEl.appendChild(slider('speed'));
      controlsEl.appendChild(slider('brightness'));
      for (const k of ['firefly_count', 'scroll_step', 'cpu_load', 'temp']) if (u.has(k)) controlsEl.appendChild(slider(k));
      const tg = [];
      if (u.has('rainbow')) tg.push(toggle('rainbow', 'Rainbow'));
      if (u.has('reverse')) tg.push(toggle('reverse', 'Reverse'));
      if (tg.length) { const w = document.createElement('div'); w.className = 'toggles'; tg.forEach((t) => w.appendChild(t)); controlsEl.appendChild(w); }
      if (cls.cat === 'Music') {
        controlsEl.appendChild(group('Music tuning', ['sensitivity', 'bass_gain', 'beat_threshold', 'smoothing', 'music_floor'].map((k) => slider(k))));
      }
    }

    function updateCli() {
      const cls = EFFECTS[r.key], u = new Set(cls.uses), p = r.p;
      let s = `rgbctl set ${r.key}`;
      if (u.has('color1')) s += ` --color1 ${p.color1.slice(1)}`;
      if (u.has('color2')) s += ` --color2 ${p.color2.slice(1)}`;
      if (u.has('speed')) s += ` --speed ${p.speed}`;
      if (p.brightness !== 100) s += ` --brightness ${p.brightness}`;
      if (u.has('rainbow') && p.rainbow) s += ' --rainbow';
      if (u.has('reverse') && p.reverse) s += ' --reverse';
      $('pg-cli').textContent = s;
    }

    // ---- audio source ----
    const syncMusicButtons = (src) => musicEl.querySelectorAll('[data-src]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.src === src)));
    const STATUS = {
      sim: 'A silent simulated beat. Press <em>Synth beat</em> to hear a loop generated live with WebAudio, or load a track from your computer (it stays on your machine).',
      synth: 'Playing a 122 BPM loop synthesised in your browser. The analyser is a port of the app’s: FFT bands, adaptive levels and bass-onset beat detection.',
    };
    musicEl.querySelectorAll('[data-src]').forEach((b) => b.addEventListener('click', () => {
      const src = b.dataset.src;
      if (src === 'sim') { Music.useSim(); syncMusicButtons('sim'); statusEl.innerHTML = STATUS.sim; }
      else if (src === 'synth') {
        if (Music.useSynth()) { syncMusicButtons('synth'); statusEl.innerHTML = STATUS.synth; }
        else statusEl.textContent = 'Your browser doesn’t support WebAudio, so the simulated signal stays on.';
      } else fileEl.click();
      r.wake(1);
    }));
    fileEl.addEventListener('change', () => {
      const f = fileEl.files && fileEl.files[0];
      if (!f) return;
      const res = Music.useFile(f);
      if (res === false) { statusEl.textContent = 'Your browser doesn’t support WebAudio.'; return; }
      syncMusicButtons('file');
      statusEl.textContent = `Playing “${f.name}” from your computer. Nothing is uploaded.`;
      if (res && res.catch) res.catch(() => { statusEl.textContent = 'That file couldn’t be played. Try an MP3, OGG or WAV.'; Music.useSim(); syncMusicButtons('sim'); });
      fileEl.value = '';
    });

    // ---- input over the canvas ----
    const cls = () => EFFECTS[r.key];
    const uses = (what) => !!(cls().input && cls().input[what]) || (what !== 'wheel' && r.key === 'presence');
    const setPointer = (e) => { const [x, y] = r.view.toVirtual(e.clientX, e.clientY); r.inp.vx = x; r.inp.vy = y; r.inp.inside = true; };
    stage.addEventListener('pointermove', (e) => { setPointer(e); r.wake(2); });
    stage.addEventListener('pointerleave', (e) => { if (e.pointerType === 'mouse') r.inp.inside = false; });
    canvas.addEventListener('pointerdown', (e) => {
      setPointer(e);
      const unit = r.um.nearestXY(r.inp.vx, r.inp.vy);
      r.inp.click(unit, e.button === 2 ? 3 : 1);
      if (e.pointerType !== 'mouse' && uses('keys')) r.inp.key();
      r.wake(3);
    });
    canvas.addEventListener('contextmenu', (e) => { if (uses('click')) e.preventDefault(); });
    let acc = 0;
    stage.addEventListener('wheel', (e) => {
      if (!uses('wheel')) return;
      e.preventDefault();
      const dy = e.deltaY;
      if (e.deltaMode !== 0 || Math.abs(dy) >= 40) r.inp.wheel(dy < 0 ? 1 : -1);
      else { acc += dy; if (Math.abs(acc) >= 60) { r.inp.wheel(acc < 0 ? 1 : -1); acc = 0; } }
      r.wake(3);
    }, { passive: false });
    wheelPad.addEventListener('click', (e) => {
      const b = e.target.closest('[data-wheel]');
      if (!b) return;
      r.inp.wheel(+b.dataset.wheel); r.wake(3);
    });
    stage.addEventListener('keydown', (e) => {
      if (e.target !== stage || e.ctrlKey || e.metaKey || e.altKey) return;
      if (['Tab', 'Escape', 'Shift', 'Control', 'Alt', 'Meta', 'CapsLock'].includes(e.key)) return;
      const c = cls();
      let used = false;
      if (uses('keys')) { r.inp.key(); used = true; }
      if (uses('wheel') && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) { r.inp.wheel(e.key === 'ArrowUp' ? 1 : -1); used = true; }
      else if (uses('pointer') && e.key.startsWith('Arrow')) {
        const st = 32;
        if (!r.inp.inside) { r.inp.inside = true; }
        if (e.key === 'ArrowLeft') r.inp.vx = clamp(r.inp.vx - st, 0, VW);
        if (e.key === 'ArrowRight') r.inp.vx = clamp(r.inp.vx + st, 0, VW);
        if (e.key === 'ArrowUp') r.inp.vy = clamp(r.inp.vy - st, 0, VH);
        if (e.key === 'ArrowDown') r.inp.vy = clamp(r.inp.vy + st, 0, VH);
        used = true;
      }
      if (uses('click') && (e.key === ' ' || e.key === 'Enter')) { r.inp.click(r.um.nearestXY(r.inp.vx, r.inp.vy), 1); used = true; }
      if (used || c.input) { e.preventDefault(); r.wake(3); }
    });

    // ---- per-frame UI: info pill + meter ----
    let uiT = 0;
    r.onFrame = (dt) => {
      uiT += dt;
      if (uiT < 0.12) return;
      uiT = 0;
      const info = r.effect.info;
      if (info) { infoEl.hidden = false; if (infoEl.textContent !== info) infoEl.textContent = info; } else infoEl.hidden = true;
      if (!musicEl.hidden) r.audio.bands.forEach((v, i) => { bars[i].style.transform = `scaleY(${(0.06 + v * 0.94).toFixed(3)})`; });
    };

    bindPause($('pg-pause'), r);
    selectMode(0);
  }

  // ======================================================================================
  // copy buttons
  // ======================================================================================
  function initCopy() {
    document.querySelectorAll('.copy').forEach((btn) => btn.addEventListener('click', async () => {
      const text = btn.parentElement.querySelector('code').textContent;
      let ok = false;
      try { await navigator.clipboard.writeText(text); ok = true; } catch (_) {
        const ta = document.createElement('textarea');
        ta.value = text; ta.setAttribute('readonly', ''); ta.style.position = 'fixed'; ta.style.opacity = '0';
        document.body.appendChild(ta); ta.select();
        try { ok = document.execCommand('copy'); } catch (__) { ok = false; }
        ta.remove();
      }
      const label = btn.querySelector('span');
      btn.classList.toggle('ok', ok);
      label.textContent = ok ? 'Copied' : 'Select & copy';
      announce(ok ? 'Command copied to clipboard' : 'Copy failed, select the command manually');
      clearTimeout(btn._t);
      btn._t = setTimeout(() => { btn.classList.remove('ok'); label.textContent = 'Copy'; }, 1800);
    }));
  }

  function initReducedMotion() {
    const onChange = () => {
      reduced = reducedMQ.matches;
      for (const r of RUNNERS) { r.playing = !reduced; r.needsDraw = true; }
      document.querySelectorAll('.stage-btn').forEach((b) => {
        b.setAttribute('aria-pressed', String(reduced));
        b.setAttribute('aria-label', reduced ? 'Play animation' : 'Pause animation');
      });
    };
    if (reducedMQ.addEventListener) reducedMQ.addEventListener('change', onChange);
  }

  function init() {
    initHero();
    initPlayground();
    initCopy();
    initReducedMotion();
    requestAnimationFrame((ts) => { last = ts; loop(ts); });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
