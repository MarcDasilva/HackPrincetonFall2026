"use client";

import { useEffect, useRef } from "react";

// Self-contained port of the "connecting" orb (a constellation that wires itself) from thinking-orbs, Jakubantalik/Libraries.dev, MIT. Constants are the library's 64px preset already resolved: count 1.35, size 0.95, speed 3.315.
const D = 64; // design size — every constant below is tuned for a 64-unit canvas
const NODES = 41;
const SIGNALS = 7;
const THR = 0.72;
const NODE_R = 0.8;
const NODE_R_DEPTH = 1.0;
const LINE_W = 0.8;
const R_MIN = 0.2;
const SPEED = 0.6;
const RS = (D / 300) ** 0.6; // radii were tuned at 300pt; sub-linear keeps small orbs legible

const hash = (a: number, b: number) => {
  const h = Math.sin(a * 12.9898 + b * 78.233) * 43758.5453;
  return h - Math.floor(h);
};
const frac = (x: number) => x - Math.floor(x);
const lerp = (a: number, b: number, f: number) => a + (b - a) * f;
const noise = (x: number, y: number) => {
  const xi = Math.floor(x), yi = Math.floor(y);
  const fx = (x - xi) ** 2 * (3 - 2 * (x - xi)), fy = (y - yi) ** 2 * (3 - 2 * (y - yi));
  const a = hash(xi, yi), b = hash(xi + 1, yi), c = hash(xi, yi + 1), d = hash(xi + 1, yi + 1);
  return a + (b - a) * fx + (c - a) * fy + (a - b - c + d) * fx * fy;
};
const fib = (i: number, n: number): [number, number, number] => {
  const y = 1 - (2 * (i + 0.5)) / n;
  const r = Math.sqrt(1 - y * y);
  const a = i * Math.PI * (3 - Math.sqrt(5));
  return [r * Math.cos(a), y, r * Math.sin(a)];
};

type P = [number, number, number];
/** A node of the "connecting" orb as drawn this frame: x, y in the 64-unit design space, z depth in [-1, 1] (near = +1). */
export type OrbNode = P;
const ink = (w: number, a: number) => {
  const g = Math.round((1 - Math.min(1, Math.max(0, w))) * 255);
  return `rgba(${g},${g},${g},${a})`;
};

/** Paints one frame in 64-unit space. Dark-theme ink only: near dots bright, far dots dim, lines first so nodes sit on top. */
function connecting(ctx: CanvasRenderingContext2D, t: number, yaw: number, out?: OrbNode[]) {
  const c = D / 2, R = c * 0.8;
  const sy = Math.sin(t * 0.12 + yaw), cy = Math.cos(t * 0.12 + yaw), st = Math.sin(0.32), ct = Math.cos(0.32);
  const proj = ([x, y, z]: P): P => {
    const x1 = x * cy + z * sy, z1 = -x * sy + z * cy;
    return [c + x1 * R, c - (y * ct - z1 * st) * R, y * st + z1 * ct];
  };
  const nodes: P[] = [];
  for (let i = 0; i < NODES; i++) {
    const d = fib(i, NODES);
    const v: P = [
      d[0] + 0.6 * (noise(i * 0.31 + 9, t * 0.24) - 0.5),
      d[1] + 0.6 * (noise(i * 0.53 + 27, t * 0.21) - 0.5),
      d[2] + 0.6 * (noise(i * 0.77 + 55, t * 0.27) - 0.5),
    ];
    const l = Math.hypot(...v);
    nodes.push([v[0] / l, v[1] / l, v[2] / l]);
  }

  for (let i = 0; i < NODES; i++) {
    for (let j = i + 1; j < NODES; j++) {
      const dist = Math.hypot(nodes[i][0] - nodes[j][0], nodes[i][1] - nodes[j][1], nodes[i][2] - nodes[j][2]);
      if (dist >= THR) continue;
      const [x1, y1, z1] = proj(nodes[i]);
      const [x2, y2, z2] = proj(nodes[j]);
      const a = (1 - dist / THR) * (0.3 + 0.55 * ((z1 + z2) / 2 + 1) / 2);
      if (a < 0.02) continue;
      ctx.strokeStyle = ink(0.42, a);
      ctx.lineWidth = Math.max(0.6, LINE_W * RS);
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(x2, y2);
      ctx.stroke();
    }
  }

  const dots: { x: number; y: number; z: number; r: number; w: number; a: number }[] = [];
  if (out) out.length = 0;
  nodes.forEach((n, i) => {
    const [x, y, z] = proj(n);
    out?.push([x, y, z]);
    const depth = (z + 1) / 2;
    dots.push({ x, y, z, r: (NODE_R + NODE_R_DEPTH * depth) * (1 + 0.25 * Math.sin(t * 1.4 + i * 2.7)) * RS, w: 0.55 - 0.45 * depth, a: 1 });
  });
  // Signals: bright packets running between randomly re-picked node pairs.
  for (let s = 0; s < SIGNALS; s++) {
    const seg = Math.floor(t * 0.55 + s * 7.31);
    const a = Math.floor(hash(seg, s * 3.1 + 1.7) * NODES), b = Math.floor(hash(seg, s * 5.7 + 4.2) * NODES);
    if (a === b) continue;
    const f = frac(t * 0.55 + s * 7.31);
    const v: P = [lerp(nodes[a][0], nodes[b][0], f), lerp(nodes[a][1], nodes[b][1], f), lerp(nodes[a][2], nodes[b][2], f)];
    const l = Math.max(1e-6, Math.hypot(...v));
    const [x, y, z] = proj([v[0] / l, v[1] / l, v[2] / l]);
    const depth = (z + 1) / 2;
    dots.push({ x, y, z, r: (NODE_R * 1.5 + NODE_R_DEPTH * depth) * RS, w: 0.05, a: 0.5 + 0.5 * depth });
  }
  dots.sort((p, q) => p.z - q.z); // far to near
  for (const d of dots) {
    ctx.fillStyle = ink(d.w, d.a);
    ctx.beginPath();
    ctx.arc(d.x, d.y, Math.max(R_MIN, d.r), 0, Math.PI * 2);
    ctx.fill();
  }
}

const TAU = Math.PI * 2, C = D / 2, R = C * 0.8;
/** Rotates about X then Y and maps into 64-unit space; z is depth in [-1, 1], near = +1. */
const view = ([x, y, z]: P, ax: number, ay: number, s = R): P => {
  const y1 = y * Math.cos(ax) - z * Math.sin(ax), z1 = y * Math.sin(ax) + z * Math.cos(ax);
  return [C + (x * Math.cos(ay) + z1 * Math.sin(ay)) * s, C - y1 * s, -x * Math.sin(ay) + z1 * Math.cos(ay)];
};
/** Paints dots far to near: near dots bigger and brighter. `k` scales the radius, `fade` the alpha. */
const paintDots = (ctx: CanvasRenderingContext2D, ds: { p: P; k: number; fade: number }[], r0: number, r1: number) => {
  ds.sort((a, b) => a.p[2] - b.p[2]);
  for (const { p: [x, y, z], k, fade } of ds) {
    const d = (z + 1) / 2;
    ctx.fillStyle = ink(0.6 - 0.6 * d, (0.2 + 0.8 * d) * fade);
    ctx.beginPath();
    ctx.arc(x, y, Math.max(R_MIN, (r0 + r1 * d) * k), 0, TAU);
    ctx.fill();
  }
};

/** Dotted sphere with a wave rolling pole to pole. */
function tidal(ctx: CanvasRenderingContext2D, t: number, yaw: number) {
  const ds = [];
  for (let i = 0; i < 260; i++) {
    const p = fib(i, 260), k = 1 + 0.13 * Math.sin(p[1] * 7 - t * 3.2);
    ds.push({ p: view([p[0] * k, p[1] * k, p[2] * k], 0.35, t * 0.25 + yaw, R * 0.88), k: (k - 0.75) * 2.4, fade: 1 });
  }
  paintDots(ctx, ds, 0.35, 0.75);
}

/** Dotted torus with a swell racing around it. */
function halo(ctx: CanvasRenderingContext2D, t: number, yaw: number) {
  const ds = [];
  for (let u = 0; u < 56; u++) for (let v = 0; v < 12; v++) {
    const a = (u / 56) * TAU, b = (v / 12) * TAU + u * 0.11;
    const sw = 1 + 0.45 * Math.max(0, Math.sin(a * 2 - t * 2.4)) ** 3, r = 0.24 * sw, q = 0.68 + r * Math.cos(b);
    ds.push({ p: view([q * Math.cos(a), r * Math.sin(b), q * Math.sin(a)], 1 + 0.15 * Math.sin(t * 0.4), t * 0.2 + yaw), k: sw, fade: 1 });
  }
  paintDots(ctx, ds, 0.3, 0.6);
}

/** Particles sailing rhumb lines from pole to pole; they fade as they converge on a pole. */
function loxodrome(ctx: CanvasRenderingContext2D, t: number, yaw: number) {
  const ds = [];
  for (let s = 0; s < 7; s++) for (let i = 0; i < 26; i++) {
    const ph = (frac(i / 26 + t * 0.05) - 0.5) * Math.PI * 0.96, c = Math.cos(ph);
    const lon = (s / 7) * TAU + 1.6 * Math.log(Math.tan(Math.PI / 4 + ph / 2));
    ds.push({ p: view([c * Math.cos(lon), Math.sin(ph), c * Math.sin(lon)], 0.3, t * 0.2 + yaw, R * 0.92), k: 0.4 + 0.6 * c, fade: Math.min(1, c * 2.5) });
  }
  paintDots(ctx, ds, 0.3, 1);
}

/** Two-armed galaxy disk, tilted, particles drifting inward. */
function nebula(ctx: CanvasRenderingContext2D, t: number, yaw: number) {
  const g = ctx.createRadialGradient(C, C, 0, C, C, 9);
  g.addColorStop(0, "rgba(255,255,255,.55)");
  g.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, D, D);
  const ds = [];
  for (let i = 0; i < 240; i++) {
    const f = frac(hash(i, 3) - t * 0.07), h = (hash(i, 8) - 0.5) * 0.22 * (1 - f);
    const a = (i % 2) * Math.PI + Math.log(f * 8 + 1) * 2.2 - t * 0.5 + (hash(i, 5) - 0.5) * 0.7;
    ds.push({ p: view([f * Math.cos(a), h, f * Math.sin(a)], 1.05 + 0.12 * Math.sin(t * 0.3), t * 0.08 + yaw), k: 0.5 + f * 0.7, fade: Math.min(1, f * 5) * 0.9 });
  }
  paintDots(ctx, ds, 0.25, 0.9);
}

// Every variant keeps its sphere inside radius R (0.8 of the canvas half-width) — Dashboard's ORB_FILL layout assumes it.
const DRAW = { connecting, tidal, halo, loxodrome, nebula };
export type OrbVariant = keyof typeof DRAW;

/** Draws the 64-unit design through a scaled context onto a backing store of `px * dpr`, so it stays vector-sharp at any size. The backing store is NEVER capped below the CSS size, or it blurs. */
/** `spin.a` is an extra yaw in radians around the vertical axis, read EVERY frame — the caller tweens the object in place (GSAP), so a new object per render would drop the tween. */
/** `nodes` is refilled EVERY frame with the "connecting" variant's dots as drawn (OrbNode); other variants leave it empty. ResearchBoxes lands its info-board dots on them. */
export default function Orb({ px, speed = 1, spin, variant = "connecting", nodes }: { px: number; speed?: number; spin?: { a: number }; variant?: OrbVariant; nodes?: { current: OrbNode[] } }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const target = useRef(speed);
  target.current = speed;
  useEffect(() => {
    const canvas = ref.current!;
    const ctx = canvas.getContext("2d")!;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    canvas.width = canvas.height = Math.round(px * dpr);
    const k = (px * dpr) / D;
    let raf = 0, t = 0, v = target.current, last = performance.now();
    const loop = () => {
      const now = performance.now(), dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      // Time is INTEGRATED, never now * speed — scaling the absolute clock jumps every node the moment speed changes. v eases toward the prop over ~0.3s.
      v += (target.current - v) * Math.min(1, dt * 3.5);
      t += dt * v;
      ctx.setTransform(k, 0, 0, k, 0, 0);
      ctx.clearRect(0, 0, D, D);
      // The new variants were tuned at 0.96 time units per second, connecting at SPEED.
      if (variant === "connecting") connecting(ctx, t * SPEED, spin?.a ?? 0, nodes?.current);
      else DRAW[variant](ctx, t * 0.96, spin?.a ?? 0);
      raf = requestAnimationFrame(loop);
    };
    loop();
    return () => cancelAnimationFrame(raf);
  }, [px, variant]);
  return <canvas ref={ref} aria-hidden style={{ width: px, height: px, display: "block" }} />;
}
