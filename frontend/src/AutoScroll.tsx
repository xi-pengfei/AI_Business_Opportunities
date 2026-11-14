import {useEffect, useRef, type ReactNode} from 'react';

/** Scroll the original rows, never cloned evidence or duplicate spider targets. */
export function AutoScroll({children, enabled = false, label}: {
  children: ReactNode; enabled?: boolean; label: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const box = ref.current;
    if (!box || !enabled) return;
    const reduced = matchMedia('(prefers-reduced-motion: reduce)');
    let raf = 0, previous = 0, position = box.scrollTop, waitUntil = performance.now() + 1500;
    const manual = () => { waitUntil = performance.now() + 6000; };
    const frame = (time: number) => {
      const elapsed = previous ? Math.min(time - previous, 50) : 0;
      previous = time;
      const max = Math.max(0, box.scrollHeight - box.clientHeight);
      const paused = reduced.matches || document.hidden || box.contains(document.activeElement) || time < waitUntil;
      if (paused || max <= 1) position = box.scrollTop;
      else if (position >= max - 0.5) {
        box.scrollTop = position = 0;
        waitUntil = time + 1800;
      } else {
        position = Math.min(max, position + elapsed * 0.018);
        box.scrollTop = position;
        if (position >= max - 0.5) waitUntil = time + 2400;
      }
      raf = requestAnimationFrame(frame);
    };
    box.addEventListener('wheel', manual, {passive:true});
    box.addEventListener('touchstart', manual, {passive:true});
    raf = requestAnimationFrame(frame);
    return () => {
      cancelAnimationFrame(raf);
      box.removeEventListener('wheel', manual);
      box.removeEventListener('touchstart', manual);
    };
  }, [enabled]);
  return <div className="table-scroll auto-scroll" ref={ref} role="region" aria-label={label} tabIndex={0}>{children}</div>;
}
