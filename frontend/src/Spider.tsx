import { useEffect, useRef, useState } from "react";
import { cargoKey, cargoText, fragmentColor, type Cargo } from "./fragments";

// The source is a document canvas: its viewport follows the spider,
// independently of the upward-looping data tables. Each delivered cargo is sought, plucked
// off the document and flown into the library; data flow stays in main.tsx.
type Hold = { x: number; y: number; el: Element; grabbable: boolean };
type Foot = { x: number; y: number };
type Leg = {
  side: number; rest: number; factor: number; group: number; col: string; seed: number;
  foot: Foot; from: Foot | null; to: Foot | null; t: number; dur: number; lift: number; hold: Hold | null;
};
type Thread = { h: Hold; col: string; until: number; pt: Foot };
type Delivery = {
  key: string | null; phase: "idle" | "seek" | "read" | "fly";
  mark: Element | null; readUntil: number; seekSince: number; text: string; color: string;
};

const COLORS = ["#ff2e88", "#39ff88", "#74d7e8", "#ffd400", "#f2f5ff"];
// White stays reserved for the body outline: a white thread reads as a stray hair.
const THREADS = ["#ff2e88", "#39ff88", "#74d7e8", "#ffd400"];
const pick = <T,>(a: T[]): T => a[(Math.random() * a.length) | 0];
const rnd = (a: number, b: number) => a + Math.random() * (b - a);
const clamp = (v: number, a: number, b: number) => Math.max(a, Math.min(b, v));

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
  const state = useRef({ searching, onDelivered });
  state.current = { searching, onDelivered };
  const [size, setSize] = useState("");
  // Physics lives across effect re-runs so the walk never resets on a new cargo.
  const world = useRef<{
    body: { x: number; y: number; vx: number; vy: number; a: number };
    goal: Foot; pause: number; holds: Hold[]; scanAt: number;
    legs: Leg[]; threads: Thread[]; grabbed: Map<Element, number>;
    last: number; nextThread: number; anchor: { el: Element; y: number } | null;
    surfacing: boolean; userAt: number;
    mood: { kind: "curious" | "alert" | "startled"; until: number; seed: number } | null; hopAt: number;
  } | null>(null);
  const delivery = useRef<Delivery>({ key: null, phase: "idle", mark: null, readUntil: 0, seekSince: 0, text: "", color: "" });

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
    if (!canvas) return;
    const key = item ? cargoKey(item) : null;
    // Visual delivery only: the item has already been committed by the backend.
    if (delivery.current.key !== key)
      delivery.current = {
        key, phase: key ? "seek" : "idle", mark: null, readUntil: 0,
        seekSince: performance.now(), text: item ? cargoText(item) : "",
        color: item ? fragmentColor(item.fragmentIndex) : "",
      };
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
      if (item) {
        const timer = setTimeout(() => { if (delivery.current.key === key) { delivery.current.phase = "idle"; state.current.onDelivered(); } }, 50);
        return () => clearTimeout(timer);
      }
      return;
    }
    // A new delivery always starts from a clean surface: no stale phase colours.
    canvas.parentElement?.querySelectorAll("[data-crawl-phase]").forEach(el => el.removeAttribute("data-crawl-phase"));
    const ctx = canvas.getContext("2d");
    const workfield = canvas.parentElement!;
    const feed = workfield.querySelector<HTMLElement>(".terminal-feed");
    if (!ctx || !feed) return;

    const w = world.current ?? (world.current = {
      body: { x: 140, y: 120, vx: 0, vy: 0, a: -Math.PI / 2 },
      goal: { x: 140, y: 120 }, pause: 0, holds: [], scanAt: 0,
      legs: [] as Leg[], threads: [] as Thread[], grabbed: new Map<Element, number>(),
      last: 0, nextThread: 600, anchor: null, surfacing: false, userAt: 0,
      mood: null, hopAt: 0,
    });
    if (!w.legs.length) {
      const angs = [0.45, 1.05, 1.75, 2.45];
      [1, -1].forEach(side => angs.forEach((a, i) => w.legs.push({
        side, rest: side * a, factor: i === 0 || i === 3 ? .82 : .7, seed: Math.random() * 7,
        group: (i + (side > 0 ? 0 : 1)) % 2, col: pick(COLORS),
        foot: { x: w.body.x, y: w.body.y }, from: null, to: null, t: 1, dur: .13, lift: 0, hold: null,
      })));
    }

    const scan = () => {
      const pr = workfield.getBoundingClientRect(), st = feed.scrollTop;
      const fr = feed.getBoundingClientRect();
      const out: Hold[] = [];
      for (const el of feed.querySelectorAll("h3, a, mark[data-source-fragment], .source-document ol li")) {
        for (const r of el.getClientRects()) {
          if (r.width < 6 || r.height < 6) continue;
          const n = Math.max(1, Math.round(r.width / 90));
          for (let i = 0; i < n; i++) out.push({
            x: r.left - pr.left + r.width * (i + .5) / n,
            y: r.top - pr.top + r.height / 2 + st,
            el, grabbable: el.tagName === "A" || el.tagName === "H3" || el.tagName === "H4",
          });
        }
      }
      // Content inserted above the spider shifts the document under its feet.
      // Re-anchor on the element it last stood on so the walk stays continuous.
      const anchor = w.anchor;
      if (anchor && anchor.el.isConnected) {
        const moved = out.find(h => h.el === anchor.el);
        if (moved) {
          const delta = moved.y - anchor.y;
          if (Math.abs(delta) > 2) {
            w.body.y += delta; w.goal.y += delta;
            for (const l of w.legs) {
              l.foot.y += delta;
              if (l.from) l.from.y += delta;
              if (l.to) l.to.y += delta;
            }
            // New content shoved the ground: recoil away, legs flare, no freeze.
            if (Math.abs(delta) > 40) {
              w.mood = { kind: "startled", until: performance.now() + 800, seed: Math.random() * 7 };
              w.body.y -= Math.sign(delta) * 22;
              w.pause = Math.max(w.pause, .35);
            }
            if (Math.abs(delta) > 60) w.threads.length = 0;
          }
          anchor.y = moved.y;
        }
      }
      w.holds = out;
      w.scanAt = performance.now() + 900;
    };
    const nearestHold = (p: Foot, r: number): Hold | null => {
      let best: Hold | null = null, bd = r;
      for (const h of w.holds) {
        const d = Math.abs(h.x - p.x) + Math.abs(h.y - p.y);
        if (d < bd) { bd = d; best = h; }
      }
      return best;
    };
    const chooseGoal = () => {
      const fr = feed.getBoundingClientRect(), pr = workfield.getBoundingClientRect();
      const top = feed.scrollTop + fr.top - pr.top;
      // Finished the page: climb back to the first hold, fast.
      if (w.surfacing && w.holds.length) {
        const first = w.holds.reduce((a, b) => b.y < a.y ? b : a);
        if (w.body.y - first.y < feed.clientHeight) w.surfacing = false;
        w.goal = { x: first.x, y: first.y };
        return;
      }
      const visible = w.holds.filter(h => h.y > top + 24 && h.y < top + feed.clientHeight - 24);
      const pool = delivery.current.phase === "idle" && Math.random() < .7 ? visible : w.holds;
      if (pool.length && Math.random() < .8) {
        const h = pick(pool); w.goal = { x: h.x, y: h.y };
      } else {
        w.goal = { x: rnd(fr.left - pr.left + 30, fr.right - pr.left - 30),
          y: rnd(top + 30, Math.max(top + 31, top + feed.clientHeight - 30)) };
      }
    };
    const grab = (el: Element, col: string) => {
      if (!(el instanceof HTMLElement) || !["A", "H3", "H4"].includes(el.tagName) || !el.isConnected) return;
      el.style.setProperty("--wc", col);
      el.classList.add("wc-grab");
      w.grabbed.set(el, performance.now() + rnd(1400, 2800));
    };
    // A human scroll borrows the viewport; the camera yields for a few seconds.
    const bumpUser = () => { w.userAt = performance.now(); };
    feed.addEventListener("wheel", bumpUser, { passive: true });
    feed.addEventListener("touchstart", bumpUser, { passive: true });

    let raf = 0;
    const frame = (now: number) => {
      raf = requestAnimationFrame(frame);
      if (document.hidden) { w.last = now; return; }
      const dt = Math.min(.05, w.last ? (now - w.last) / 1000 : .016);
      w.last = now;
      if (now > w.scanAt) scan();

      const S = Math.max(.8, Math.min(1.4, Math.min(canvas.clientWidth, canvas.clientHeight) / 640));
      const startled = w.mood?.kind === "startled" && now < w.mood.until;
      // A startled spider flares every leg outward before recoiling.
      const REACH = 104 * S * (startled ? 1.18 : 1);
      const pr = workfield.getBoundingClientRect(), fr = feed.getBoundingClientRect();
      const fx = fr.left - pr.left, fw = fr.width, fh = fr.height;
      const docMax = Math.max(240, feed.scrollHeight);
      const d0 = delivery.current;
      // Waiting for the next item is not idle time: the spider patrols at full
      // pace so the page never goes still.
      const act = state.current.searching || d0.phase === "idle" ? 1 : .62;

      // ---- cargo phases: seek → read → fly; the walk itself stays organic ----
      if (d0.phase === "seek" && d0.key) {
        const mark = feed.querySelector(`mark[data-source-fragment="${d0.key}"]`);
        d0.mark = mark;
        if (mark) {
          const r = (mark as HTMLElement).getBoundingClientRect();
          w.goal = { x: r.left - pr.left + r.width / 2, y: r.top - pr.top + r.height / 2 + feed.scrollTop };
        } else if (now - d0.seekSince > 3000) {
          delivery.current = { ...d0, phase: "idle", key: null, mark: null };
          state.current.onDelivered(); // DOM mismatch guard: never stall the queue
          return;
        }
      }
      const dx = w.goal.x - w.body.x, dy = w.goal.y - w.body.y, dist = Math.hypot(dx, dy);
      if (d0.phase === "seek" && dist < 16 * S) {
        d0.phase = "read";
        d0.readUntil = now + 900;
        if (d0.mark) {
          grab(d0.mark, d0.color);
          (d0.mark as HTMLElement).dataset.crawlPhase = "highlight";
        }
        w.pause = .9;
      } else if (d0.phase === "read" && now >= d0.readUntil && d0.mark) {
        (d0.mark as HTMLElement).dataset.crawlPhase = "pluck";
        const target =
          workfield.querySelector(`[data-library-item="${item?.id}"] [data-field="${item?.field}"]`) ||
          workfield.querySelector(`[data-inbox-field="${item?.field}"]`);
        const tr = (target as HTMLElement | null)?.getBoundingClientRect();
        const mr = (d0.mark as HTMLElement).getBoundingClientRect();
        const frag = document.createElement("div");
        frag.className = "spider-frag";
        frag.textContent = d0.text;
        frag.style.cssText += `left:${mr.left}px;top:${mr.top}px;background:${d0.color};`;
        document.body.appendChild(frag);
        const tx = tr ? tr.left + tr.width / 2 - mr.left : fw * .7;
        const ty = tr ? tr.top + tr.height / 2 - mr.top : 60;
        const fly = frag.animate([
          { transform: "translate(0,0) scale(1) rotate(-2deg)", opacity: 1 },
          { transform: `translate(${(tx - mr.width) / 2}px,${(ty - mr.height) / 2 - 40}px) scale(1.5) rotate(3deg)`, opacity: 1, offset: .45 },
          { transform: `translate(${tx - mr.width / 2}px,${ty - mr.height / 2}px) scale(.45) rotate(0deg)`, opacity: .1 },
        ], { duration: 950, easing: "cubic-bezier(.3,.6,.3,1)", fill: "forwards" });
        fly.onfinish = () => {
          frag.remove();
          setTimeout(() => { if (d0.mark) delete (d0.mark as HTMLElement).dataset.crawlPhase; }, 700);
          if (delivery.current.key === d0.key) { delivery.current.phase = "idle"; delivery.current.mark = null; }
          state.current.onDelivered();
        };
        d0.phase = "fly";
        w.hopAt = now; // a little hop of victory before the strip flies off
        chooseGoal();
      }

      // ---- wander: acceleration, easing, walk-and-stop ----
      if (w.pause > 0) w.pause -= dt;
      else {
        // A far target is a dash, a near one is a crawl: keeps the queue moving
        // without ever looking like a tween.
        const base = d0.phase === "seek" ? clamp(130 + dist * 1.2, 180, 720)
          : w.surfacing ? 320 : 185 * act;
        const sp = base * S * Math.min(1, dist / 80);
        w.body.vx += ((dx / (dist || 1)) * sp - w.body.vx) * Math.min(1, dt * 3);
        w.body.vy += ((dy / (dist || 1)) * sp - w.body.vy) * Math.min(1, dt * 3);
        if (dist < 12 && d0.phase !== "seek") {
          w.pause = d0.phase === "idle" ? rnd(.1, .4) : rnd(.12, .5);
          if (w.body.y > docMax - fh) w.surfacing = true;
          chooseGoal();
        }
      }
      if (w.pause > 0) { w.body.vx *= .9; w.body.vy *= .9; }
      w.body.x = clamp(w.body.x + w.body.vx * dt, fx + 18, fx + fw - 18);
      w.body.y = clamp(w.body.y + w.body.vy * dt, 20, docMax - 20);
      const spd = Math.hypot(w.body.vx, w.body.vy);
      if (spd > 5) {
        let da = Math.atan2(w.body.vy, w.body.vx) - w.body.a;
        da = Math.atan2(Math.sin(da), Math.cos(da));
        w.body.a += da * Math.min(1, dt * 6);
      }

      // Follow the spider down the document: push the viewport only far enough
      // to bring it back inside the band — never re-center, so there is no
      // swim-back. A recent user scroll borrows the camera for a few seconds.
      const anchorY = (d0.phase === "seek" && d0.mark ? w.goal.y : w.body.y) + w.body.vy * .22;
      const fy = fr.top - pr.top;
      const localY = anchorY - feed.scrollTop - fy;
      let cam = feed.scrollTop;
      if (localY < fh * .26) cam = anchorY - fy - fh * .26;
      if (localY > fh * .55) cam = anchorY - fy - fh * .55;
      if (now - w.userAt > 3000) {
        cam = clamp(cam, 0, Math.max(0, feed.scrollHeight - fh));
        // Near the edge the camera sprints, so a dash never outruns the view.
        const urgent = localY < 24 || localY > fh - 24;
        feed.scrollTop += (cam - feed.scrollTop) * Math.min(1, dt * (urgent ? 9 : 4));
        // Hard guarantee: a shrunken document or replaced articles can leave the
        // spider stranded outside the viewport — pull it and its feet back in.
        const sy = w.body.y - feed.scrollTop - fy;
        if (sy < 10 || sy > fh - 10) {
          const snap = clamp(sy, 10, fh - 10) - sy;
          w.body.y += snap; w.goal.y += snap;
          if (w.anchor) w.anchor.y += snap;
          for (const l of w.legs) {
            l.foot.y += snap;
            if (l.from) l.from.y += snap;
            if (l.to) l.to.y += snap;
          }
        }
      }

      // Restless feet: during a pause an occasional random re-step keeps the
      // silhouette alive — it never parks.
      if (d0.phase === "idle" && w.pause > 0 && Math.random() < dt * .6) {
        const idle = w.legs.filter(l => l.t === 1);
        if (idle.length) {
          const l = pick(idle);
          l.from = l.foot;
          l.to = { x: l.foot.x + rnd(-16, 16), y: l.foot.y + rnd(-16, 16) };
          l.dur = .13; l.t = 0; l.hold = null;
        }
      }

      // ---- gait: two-segment IK, alternating groups, feet snap to holds ----
      const stepping = [0, 0];
      w.legs.forEach(l => { if (l.t < 1) stepping[l.group]++; });
      // The look-ahead must stay inside the reach, or a fast dash sets a foot
      // target the leg can never satisfy and every step is truncated.
      const lead = {
        x: clamp(w.body.vx * .16, -REACH * .26, REACH * .26),
        y: clamp(w.body.vy * .16, -REACH * .26, REACH * .26),
      };
      for (const l of w.legs) {
        if (l.t < 1) {
          l.t = Math.min(1, l.t + dt / l.dur);
          const e = l.t * l.t * (3 - 2 * l.t);
          l.foot = { x: l.from!.x + (l.to!.x - l.from!.x) * e, y: l.from!.y + (l.to!.y - l.from!.y) * e };
          l.lift = Math.sin(l.t * Math.PI);
          if (l.t === 1) {
            l.lift = 0;
            if (l.hold) {
              grab(l.hold.el, l.col);
              w.anchor = { el: l.hold.el, y: l.hold.y };
              // Content shapes mood: a link is worth a sniff, a heading is a find.
              const tag = l.hold.el.tagName;
              if (tag === "A" && Math.random() < .55) w.mood = { kind: "curious", until: now + 1100, seed: Math.random() * 7 };
              else if ((tag === "H3" || tag === "H4") && Math.random() < .7) w.mood = { kind: "alert", until: now + 1400, seed: Math.random() * 7 };
            }
          }
          continue;
        }
        const ha = w.body.a + l.rest * .35;
        const hip = { x: w.body.x + Math.cos(ha) * 11 * S, y: w.body.y + Math.sin(ha) * 11 * S };
        const ia = w.body.a + l.rest, llen = REACH * l.factor;
        const idl = { x: w.body.x + Math.cos(ia) * llen, y: w.body.y + Math.sin(ia) * llen };
        const lag = Math.hypot(l.foot.x - hip.x, l.foot.y - hip.y);
        // A leg longer than its own segments cannot be drawn without turning into
        // a rubber band; a foot that far gone must step regardless of the other
        // group, or the dash leaves permanent straight lines behind it.
        const tooFar = Math.hypot(l.foot.x - idl.x, l.foot.y - idl.y) > REACH * .45
          || lag > REACH * .98;
        const urgent = lag > REACH * .8;
        if (tooFar && (urgent || (stepping[l.group] < 4 && stepping[1 - l.group] === 0))) {
          const tgt = { x: idl.x + lead.x, y: idl.y + lead.y };
          const hd = nearestHold(tgt, REACH * .55);
          l.hold = hd;
          l.from = l.foot;
          l.to = hd ? { x: hd.x, y: hd.y } : tgt;
          // long reaches swing faster so a big correction never reads as a drag
          l.dur = clamp(.09 + Math.hypot(l.to.x - l.from.x, l.to.y - l.from.y) / 2600, .09, .19);
          l.t = 0;
          stepping[l.group]++;
        }
      }

      // ---- silk threads toward other holds ----
      if (now > w.nextThread && w.holds.length && d0.phase !== "fly") {
        const near = w.holds.filter(h => Math.abs(h.y - w.body.y) < 260);
        const h = pick(near.length ? near : w.holds);
        w.threads.push({ h, col: pick(THREADS), until: now + rnd(600, 1300), pt: { x: w.body.x, y: w.body.y } });
        grab(h.el, w.threads[w.threads.length - 1].col);
        w.nextThread = now + (state.current.searching ? rnd(800, 1800) : rnd(1300, 2600));
      }
      // Silk has elasticity: the far end trails the anchor with a short lag.
      for (const th of w.threads) {
        th.pt.x += (th.h.x - th.pt.x) * Math.min(1, dt * 7);
        th.pt.y += (th.h.y - th.pt.y) * Math.min(1, dt * 7);
      }
      for (let i = w.threads.length - 1; i >= 0; i--) if (now > w.threads[i].until) w.threads.splice(i, 1);
      for (const [el, t] of w.grabbed) if (now > t) { el.classList.remove("wc-grab"); w.grabbed.delete(el); }

      // ---- render (feed doc space: subtract scrollTop) ----
      const dpr = Math.min(devicePixelRatio || 1, 2);
      const bw = Math.round(canvas.clientWidth * dpr), bh = Math.round(canvas.clientHeight * dpr);
      if (canvas.width !== bw || canvas.height !== bh) { canvas.width = bw; canvas.height = bh; }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, canvas.clientWidth, canvas.clientHeight);
      // The document is the spider's page: legs and silk stay inside its frame.
      ctx.save();
      ctx.beginPath(); ctx.rect(fx, fy, fw, fh); ctx.clip();
      ctx.lineCap = "round";
      const TH = 46 * S, SH = 58 * S;
      const off = feed.scrollTop;
      // ---- character: moods bend the pose; squash & stretch bends the body ----
      const mo = w.mood && now < w.mood.until ? w.mood.kind : (w.mood = null);
      const hopAge = (now - w.hopAt) / 460;
      const hop = hopAge >= 0 && hopAge < 1 ? Math.sin(hopAge * Math.PI) * 8 * S : 0;
      let wob = 0;
      if (mo === "alert") wob = Math.sin(now / 70 + (w.mood?.seed ?? 0)) * .07;    // found something big
      else if (mo === "curious") wob = Math.sin(now / 110 + (w.mood?.seed ?? 0)) * .04; // sniffing a link
      if (d0.phase === "read") wob = Math.sin(now / 150) * .05;                    // reads line by line
      const bx = w.body.x, by = w.body.y - off - hop;
      // A soft pool of shadow under the spider keeps the text it crosses legible.
      const shade = ctx.createRadialGradient(bx, by, 8 * S, bx, by, 74 * S);
      shade.addColorStop(0, "rgba(0,0,0,.5)");
      shade.addColorStop(1, "rgba(0,0,0,0)");
      ctx.fillStyle = shade;
      ctx.fillRect(bx - 74 * S, by - 74 * S, 148 * S, 148 * S);
      for (const th of w.threads) {
        ctx.strokeStyle = th.col; ctx.globalAlpha = .8; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(bx, by); ctx.lineTo(th.pt.x, th.pt.y - off); ctx.stroke();
      }
      ctx.globalAlpha = 1;
      const joints: [Foot, string, number][] = [];
      const LEGMAX = (TH + SH) * .92;
      for (const l of w.legs) {
        const ha = w.body.a + l.rest * .35;
        const hip = { x: bx + Math.cos(ha) * 9 * S, y: by + Math.sin(ha) * 9 * S };
        const fv = {
          x: l.foot.x + (hip.x - l.foot.x) * l.lift * .18,
          y: l.foot.y - off + (hip.y - (l.foot.y - off)) * l.lift * .18 - l.lift * 10 * S,
        };
        // Hard ceiling on drawn leg length: a foot that drifted out of reach is
        // pulled back along its own axis instead of stretching into a straight line.
        const span = Math.hypot(fv.x - hip.x, fv.y - hip.y) || 1;
        if (span > LEGMAX) {
          const k = LEGMAX / span;
          fv.x = hip.x + (fv.x - hip.x) * k;
          fv.y = hip.y + (fv.y - hip.y) * k;
        }
        // Spider legs arch: the joint sits outside the hip→foot chord. Each leg
        // breathes on its own phase, so the line-work never settles into geometry.
        const mx = (hip.x + fv.x) / 2, my = (hip.y + fv.y) / 2;
        const nx = -(fv.y - hip.y) / span, ny = (fv.x - hip.x) / span;
        const bow = (Math.min(span, LEGMAX) * .34 + 8 * S) * (1 + Math.sin(now / 900 + l.seed) * .14);
        const k = { x: mx + nx * bow * l.side, y: my + ny * bow * l.side };
        const sc = l.t < 1 ? l.col : "rgba(200,212,255,.9)";
        ctx.strokeStyle = sc;
        ctx.lineWidth = 1.5 * S;
        ctx.beginPath(); ctx.moveTo(hip.x, hip.y); ctx.lineTo(k.x, k.y); ctx.stroke();
        ctx.lineWidth = 1.05 * S;
        ctx.beginPath(); ctx.moveTo(k.x, k.y); ctx.lineTo(fv.x, fv.y); ctx.stroke();
        joints.push([k, "#ff2e88", 2.2], [fv, l.hold ? "#39ff88" : "#ff2e88", 1.9]);
      }
      // body: a slender white wireframe — the suggestion of a spider, not one
      ctx.save();
      ctx.translate(bx, by); ctx.rotate(w.body.a + Math.PI / 2 + wob);
      const stg = clamp(spd * .0005, 0, .12) + hop / (60 * S);
      ctx.scale(1 - stg * .45, 1 + stg);
      ctx.strokeStyle = "#ffffff"; ctx.lineWidth = 1.5;
      ctx.fillStyle = "rgba(4,12,52,.72)";
      ctx.beginPath(); ctx.roundRect(-7 * S, -9 * S, 14 * S, 18 * S, 2.5 * S); ctx.fill(); ctx.stroke();
      ctx.strokeStyle = "#74d7e8";
      ctx.beginPath(); ctx.rect(-4 * S, 9 * S, 8 * S, 14 * S); ctx.stroke();
      ctx.fillStyle = "#ff2e88";
      ctx.beginPath(); ctx.arc(0, -2 * S, 3 * S, 0, 7); ctx.fill();
      ctx.strokeStyle = "#ffd400"; ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(-3 * S, -9 * S); ctx.lineTo(-5 * S, -15 * S);
      ctx.moveTo(3 * S, -9 * S); ctx.lineTo(5 * S, -15 * S);
      ctx.stroke();
      ctx.restore();
      for (const [p, c, r] of joints) {
        // A joint that lands on the body would read as a spot, not a limb.
        if (Math.hypot(p.x - bx, p.y - by) < 13 * S) continue;
        ctx.fillStyle = c; ctx.beginPath(); ctx.arc(p.x, p.y, r * S, 0, 7); ctx.fill();
      }
      // the plucked strip rides in the jaws until the flight begins
      if (d0.phase === "read" && d0.text) {
        ctx.font = "12px 'PingFang SC',system-ui";
        const tw = Math.min(230, ctx.measureText(d0.text).width) + 16;
        const sx = clamp(w.body.x + 12 * S, fx + 4, fx + fw - tw - 4);
        const sy = w.body.y - off + 22 * S;
        ctx.fillStyle = d0.color;
        ctx.fillRect(sx, sy, tw, 22);
        ctx.strokeStyle = "rgba(2,12,58,.85)";
        ctx.lineWidth = 1;
        ctx.strokeRect(sx + .5, sy + .5, tw - 1, 21);
        ctx.fillStyle = "#151217";
        ctx.fillText(d0.text.slice(0, 40), sx + 8, sy + 15);
      }
      ctx.restore();
    };
    raf = requestAnimationFrame(frame);
    return () => {
      cancelAnimationFrame(raf);
      feed.removeEventListener("wheel", bumpUser);
      feed.removeEventListener("touchstart", bumpUser);
      const c = canvas.getContext("2d");
      c?.clearRect(0, 0, canvas.width, canvas.height);
    };
  }, [item ? cargoKey(item) : null, size]);

  return <canvas className="spider" ref={ref} aria-hidden="true" />;
}
