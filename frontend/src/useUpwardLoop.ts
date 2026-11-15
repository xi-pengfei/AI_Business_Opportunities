import {useEffect, useRef, useState, type RefObject} from 'react';
import {flushSync} from 'react-dom';

/** Recycle original keyed rows only after they leave the viewport; no duplicate targets. */
export function useUpwardLoop(boxRef: RefObject<HTMLDivElement | null>, selector: string, enabled: boolean, peerRef?: RefObject<HTMLDivElement | null>) {
  const [offset, setOffset] = useState(0);
  const turns = useRef(0);
  useEffect(() => {
    const box = boxRef.current;
    if (!box || !enabled) return;
    const reduced = matchMedia('(prefers-reduced-motion: reduce)');
    let raf = 0, previous = 0, position = box.scrollTop, waitUntil = performance.now() + 1200;
    const manual = () => { waitUntil = performance.now() + 6000; position = box.scrollTop; };
    const frame = (now: number) => {
      const elapsed = previous ? Math.min(now - previous, 50) : 0;
      previous = now;
      const peer = peerRef?.current;
      const hovered = [box, peer].some(el => el?.matches(':hover'));
      const focused = [box, peer].some(el => el && (el.matches(':focus-visible') || el.querySelector(':focus-visible')));
      const rows = box.querySelectorAll<HTMLElement>(selector);
      const max = Math.max(0, box.scrollHeight - box.clientHeight);
      if (reduced.matches || document.hidden || hovered || focused || now < waitUntil || rows.length < 2 || max < 1) position = box.scrollTop;
      else {
        const first = rows[0], second = rows[1];
        const stride = second.getBoundingClientRect().top - first.getBoundingClientRect().top;
        position = Math.min(max, position + elapsed * .009);
        if (stride > 0 && position >= stride && max >= stride) {
          position -= stride;
          flushSync(() => setOffset(++turns.current));
          box.dispatchEvent(new CustomEvent('looprotate', {detail: {distance: stride}}));
        }
        box.scrollTop = position;
        if (peer) peer.scrollTop = box.scrollTop;
      }
      raf = requestAnimationFrame(frame);
    };
    const boxes = [box, peerRef?.current].filter((el): el is HTMLDivElement => !!el);
    for (const el of boxes) {
      el.addEventListener('wheel', manual, {passive:true});
      el.addEventListener('touchstart', manual, {passive:true});
      el.addEventListener('pointerdown', manual);
    }
    raf = requestAnimationFrame(frame);
    return () => {
      cancelAnimationFrame(raf);
      for (const el of boxes) {
        el.removeEventListener('wheel', manual);
        el.removeEventListener('touchstart', manual);
        el.removeEventListener('pointerdown', manual);
      }
    };
  }, [boxRef, selector, enabled, peerRef]);
  return offset;
}
export function rotateRows<T>(rows: T[], offset: number): T[] {
  if (!rows.length) return rows;
  const start = offset % rows.length;
  return [...rows.slice(start), ...rows.slice(0, start)];
}
