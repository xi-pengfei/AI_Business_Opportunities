import { useEffect, useRef, useState } from "react";
import type { Item } from "./types";
// Visual delivery only: the item has already been committed by the backend.
export function Spider({ item }: { item: Item | null }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const [size, setSize] = useState("");
  useEffect(() => {
    const parent = ref.current?.parentElement;
    if (!parent) return;
    const observer = new ResizeObserver(([entry]) => {
      setSize(`${entry.contentRect.width}:${entry.contentRect.height}`);
    });
    observer.observe(parent);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas || matchMedia("(prefers-reduced-motion: reduce)").matches)
      return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const parent = canvas.parentElement!;
    const r = parent.getBoundingClientRect();
    const ratio = Math.min(devicePixelRatio, 2);
    canvas.width = r.width * ratio;
    canvas.height = r.height * ratio;
    ctx.scale(ratio, ratio);
    const small = r.width < 700;
    const from = { x: Math.min(150, r.width / 4), y: 170 },
      to = { x: small ? r.width * 0.6 : r.width * 0.55, y: small ? 420 : 170 };
    let raf = 0,
      start = 0;
    const feet = Array.from({ length: 8 }, () => ({ x: 0, y: 0, init: false }));
    function draw(now: number) {
      if (!ctx || !canvas) return;
      if (!start) start = now;
      const elapsed = (now - start) / 1000;
      const p = item ? Math.min(1, elapsed / 7) : 0;
      const travel =
          p > 0.82
            ? Math.max(0, (1 - p) / 0.18)
            : Math.max(0, Math.min(1, (p - 0.15) / 0.6)),
        q = travel * travel * (3 - 2 * travel),
        x = from.x + (to.x - from.x) * q,
        y = from.y + (to.y - from.y) * q;
      ctx.clearRect(0, 0, r.width, r.height);
      ctx.lineWidth = 1.2;
      ctx.strokeStyle = `hsl(${195 + 40 * Math.sin(elapsed)} 60% 74%)`;
      for (let i = 0; i < 8; i++) {
        const side = i < 4 ? -1 : 1,
          j = i % 4,
          hx = x + (j - 1.5) * 5,
          hy = y + side * 4,
          rx = x + [65, 26, -26, -65][j],
          ry = y + side * [40, 70, 70, 40][j],
          f = feet[i];
        if (!f.init) {
          f.x = rx;
          f.y = ry;
          f.init = true;
        }
        if (
          Math.hypot(rx - f.x, ry - f.y) > 22 &&
          Math.floor(elapsed * 7) % 2 === i % 2
        ) {
          f.x += (rx - f.x) * 0.4;
          f.y += (ry - f.y) * 0.4;
        }
        const dx = f.x - hx,
          dy = f.y - hy,
          d = Math.min(100, Math.max(1, Math.hypot(dx, dy))),
          a =
            Math.atan2(dy, dx) +
            side *
              (j < 2 ? -1 : 1) *
              Math.acos(
                Math.max(
                  -1,
                  Math.min(1, (48 * 48 + d * d - 58 * 58) / (96 * d)),
                ),
              ),
          kx = hx + Math.cos(a) * 48,
          ky = hy + Math.sin(a) * 48;
        ctx.beginPath();
        ctx.moveTo(hx, hy);
        ctx.lineTo(kx, ky);
        ctx.lineTo(f.x, f.y);
        ctx.stroke();
        ctx.fillStyle = "#e393b0";
        ctx.beginPath();
        ctx.arc(f.x, f.y, 1.8, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.fillStyle = "#080a0d";
      ctx.beginPath();
      ctx.moveTo(x - 22, y);
      ctx.lineTo(x - 8, y - 8);
      ctx.lineTo(x + 18, y - 5);
      ctx.lineTo(x + 25, y);
      ctx.lineTo(x + 10, y + 7);
      ctx.lineTo(x - 14, y + 6);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
      if (item && p > 0.12 && p < 0.82) {
        const message = (item!.text || item!.title).slice(0, 23);
        ctx.font = "12px system-ui";
        const tw = Math.min(ctx.measureText(message).width + 16, r.width - 16);
        ctx.fillStyle = "#70c3ce";
        ctx.fillRect(Math.min(x, r.width - tw), y + 22, tw, 28);
        ctx.fillStyle = "#10181d";
        ctx.fillText(message, Math.min(x, r.width - tw) + 8, y + 41, tw - 16);
      }
      if (item && p < 1) raf = requestAnimationFrame(draw);
    }
    raf = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(raf);
      ctx.clearRect(0, 0, r.width, r.height);
    };
  }, [item, size]);
  return <canvas className="spider" ref={ref} aria-hidden="true" />;
}
