import { useEffect, useRef, useState } from "react";
import { cargoKey, fragmentColor, type Cargo } from "./fragments";
// Visual delivery only: the item has already been committed by the backend.
export function Spider({
  item,
  searching = false,
  onDelivered,
}: {
  item: Cargo | null;
  searching?: boolean;
  onDelivered: () => void;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const state = useRef({searching, onDelivered});
  state.current = {searching, onDelivered};
  const delivery = useRef<{id: string | null; start: number; done: boolean}>({id: null, start: 0, done: false});
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
    const cargo = item;
    if (delivery.current.id !== (item ? cargoKey(item) : null)) delivery.current = {id: item ? cargoKey(item) : null, start: 0, done: false};
    const canvas = ref.current;
    if (!canvas) return;
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
      if (cargo && !delivery.current.done) {
        const timer = setTimeout(() => { delivery.current.done = true; state.current.onDelivered(); }, 50);
        return () => clearTimeout(timer);
      }
      return;
    }
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const parent = canvas.parentElement!;
    const r = parent.getBoundingClientRect();
    const ratio = Math.min(devicePixelRatio, 2);
    canvas.width = r.width * ratio;
    canvas.height = r.height * ratio;
    ctx.scale(ratio, ratio);
    const source = cargo ? parent.querySelector<HTMLElement>(`[data-source-fragment="${cargoKey(cargo)}"]`) : null;
    const box = parent.querySelector<HTMLElement>('.terminal-feed');
    if (source && box) box.scrollTop += source.getBoundingClientRect().top - box.getBoundingClientRect().top - 65;
    const sr = source?.getBoundingClientRect();
    const target = parent.querySelector('[data-inbox-target]')?.getBoundingClientRect();
    const from = {x: sr ? sr.left - r.left + Math.min(sr.width / 2, 130) : 160, y: sr ? sr.top - r.top + 8 : 170};
    const to = {x: target ? target.left - r.left + target.width / 2 : r.width * .7, y: target ? target.bottom - r.top + 48 : 150};
    const fragment = cargo?.fragments?.find(f => f.index === cargo.fragmentIndex);
    let raf = 0,
      start = 0;
    const feet = Array.from({ length: 8 }, () => ({ x: 0, y: 0, init: false }));
    function draw(now: number) {
      if (!ctx || !canvas) return;
      if (!start) start = now;
      if (cargo && !delivery.current.start) delivery.current.start = now;
      const elapsed = (now - start) / 1000;
      const p = cargo ? Math.min(1, (now - delivery.current.start) / 4500) : 0;
      const travel = Math.max(0, Math.min(1, (p - 0.18) / 0.72)),
        q = travel * travel * (3 - 2 * travel),
        x = from.x + (to.x - from.x) * q,
        y = from.y + (to.y - from.y) * q;
      canvas.dataset.phase = cargo ? p < .18 ? "highlight" : p < .9 ? "carrying" : "landing" : "waiting";
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
      if (cargo && fragment && p > 0.18 && p < 1) {
        ctx.font = "12px system-ui";
        const lines: string[] = [];
        let line = '';
        for (const char of fragment.text) {
          if (ctx.measureText(line + char).width > 255) { lines.push(line); line = ''; }
          line += char;
        }
        if (line) lines.push(line);
        const tw = Math.max(...lines.map(l => ctx.measureText(l).width)) + 18;
        const tx = Math.max(8, Math.min(x - tw / 2, r.width - tw - 8));
        ctx.fillStyle = fragmentColor(cargo.fragmentIndex);
        ctx.fillRect(tx, y + 18, tw, lines.length * 18 + 10);
        ctx.fillStyle = "#10181d";
        lines.forEach((l, i) => ctx.fillText(l, tx + 9, y + 36 + i * 18));
      }
      if (cargo && p >= 1 && !delivery.current.done) {
        delivery.current.done = true;
        state.current.onDelivered();
      }
      if (cargo && p < 1) raf = requestAnimationFrame(draw);
    }
    raf = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(raf);
      ctx.clearRect(0, 0, r.width, r.height);
    };
  }, [item ? cargoKey(item) : null, size]);
  return <canvas className="spider" ref={ref} aria-hidden="true" />;
}
