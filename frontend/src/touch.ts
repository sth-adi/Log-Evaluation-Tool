import type uPlot from "uplot";
import { extentOf, useStore } from "./store";

/**
 * Finger gestures for a plot, since uPlot only listens for the mouse.
 *  - one finger, drag along: scrub the cursor (every plot follows, the readout updates);
 *  - two fingers: pinch to zoom, move together to pan;
 *  - double tap: show everything again.
 * Vertical swipes are left to the browser (touch-action: pan-y on the plot), so the page still scrolls.
 */
export function attachTouch(u: uPlot): () => void {
  const over = u.over;
  let pinch: { d: number; cx: number; min: number; max: number } | null = null;
  let lastTap = { t: 0, x: 0, y: 0 };
  let moved = false;

  const local = (t: Touch) => {
    const r = over.getBoundingClientRect();
    return { x: t.clientX - r.left, y: t.clientY - r.top, w: r.width };
  };
  const place = (t: Touch) => {
    const p = local(t);
    u.setCursor({ left: Math.max(0, Math.min(p.w, p.x)), top: Math.max(0, p.y) });
  };
  const span = () => {
    const x = u.scales.x;
    return { min: x.min ?? 0, max: x.max ?? 1 };
  };
  const measure = (e: TouchEvent) => {
    const a = local(e.touches[0]);
    const b = local(e.touches[1]);
    return { d: Math.max(Math.hypot(a.x - b.x, a.y - b.y), 1), cx: (a.x + b.x) / 2, w: a.w };
  };

  const start = (e: TouchEvent) => {
    moved = false;
    if (e.touches.length === 2) {
      const m = measure(e);
      pinch = { d: m.d, cx: m.cx, ...span() };
    } else if (e.touches.length === 1) {
      pinch = null;
      place(e.touches[0]);
    }
  };

  const move = (e: TouchEvent) => {
    moved = true;
    if (e.touches.length === 2 && pinch) {
      const m = measure(e);
      const [e0, e1] = extentOf(useStore.getState().sources);
      const full = Math.max(e1 - e0, 1e-6);
      const span0 = pinch.max - pinch.min;
      const next = Math.min(full, Math.max(full / 2000, span0 * (pinch.d / m.d)));
      const anchor = pinch.min + (pinch.cx / m.w) * span0; // the value under the fingers when they landed
      let lo = anchor - (m.cx / m.w) * next;
      lo = Math.max(e0, Math.min(e1 - next, lo));
      u.setScale("x", { min: lo, max: lo + next });
    } else if (e.touches.length === 1 && !pinch) {
      place(e.touches[0]);
    }
  };

  const end = (e: TouchEvent) => {
    if (e.touches.length === 0) {
      if (!moved && e.changedTouches.length === 1) {
        const t = e.changedTouches[0];
        const now = Date.now();
        if (now - lastTap.t < 320 && Math.hypot(t.clientX - lastTap.x, t.clientY - lastTap.y) < 30) {
          const [a, b] = extentOf(useStore.getState().sources);
          useStore.getState().setView(null);
          u.setScale("x", { min: a, max: b });
          lastTap = { t: 0, x: 0, y: 0 };
        } else {
          lastTap = { t: now, x: t.clientX, y: t.clientY };
        }
        if (e.cancelable) e.preventDefault(); // we handled the tap; no stray mouse events after it
      }
      pinch = null;
    } else if (e.touches.length === 1) {
      pinch = null; // one finger left after a pinch: carry on as a scrub from here
      place(e.touches[0]);
    }
  };

  over.addEventListener("touchstart", start, { passive: true });
  over.addEventListener("touchmove", move, { passive: true });
  over.addEventListener("touchend", end, { passive: false });
  over.addEventListener("touchcancel", () => (pinch = null), { passive: true });
  return () => {
    over.removeEventListener("touchstart", start);
    over.removeEventListener("touchmove", move);
    over.removeEventListener("touchend", end);
  };
}
