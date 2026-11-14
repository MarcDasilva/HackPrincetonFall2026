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

/** Paints one frame in 64-unit space. Dark-theme ink only: near dots bright, far dots dim, lines first so nodes sit on top. */
function draw(ctx: CanvasRenderingContext2D, t: number) {
  const c = D / 2, R = c * 0.8;
  const sy = Math.sin(t * 0.12), cy = Math.cos(t * 0.12), st = Math.sin(0.32), ct = Math.cos(0.32);
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
  const ink = (w: number, a: number) => {
    const g = Math.round((1 - Math.min(1, Math.max(0, w))) * 255);
    return `rgba(${g},${g},${g},${a})`;
  };
  ctx.clearRect(0, 0, D, D);

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
  nodes.forEach((n, i) => {
    const [x, y, z] = proj(n);
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

/** Draws the 64-unit design through a scaled context onto a backing store of `px * dpr`, so it stays vector-sharp at any size. The backing store is NEVER capped below the CSS size, or it blurs. */
export default function Orb({ px }: { px: number }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current!;
    const ctx = canvas.getContext("2d")!;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    canvas.width = canvas.height = Math.round(px * dpr);
    const k = (px * dpr) / D;
    let raf = 0;
    const loop = () => {
      ctx.setTransform(k, 0, 0, k, 0, 0);
      draw(ctx, (performance.now() / 1000) * SPEED);
      raf = requestAnimationFrame(loop);
    };
    loop();
    return () => cancelAnimationFrame(raf);
  }, [px]);
  return <canvas ref={ref} aria-hidden style={{ width: px, height: px, display: "block" }} />;
}
