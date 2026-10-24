import { extentOf, useStore } from "./store";

/** The part of the timeline an analysis should use: the zoomed window if there is one, otherwise everything. */
export function useWindow() {
  const sources = useStore((s) => s.sources);
  const view = useStore((s) => s.view);
  const rev = useStore((s) => s.rev);
  const [e0, e1] = extentOf(sources);
  const zoomed = view != null && (Math.abs(view[0] - e0) > 1e-6 || Math.abs(view[1] - e1) > 1e-6);
  return {
    rev,
    zoomed,
    t0: zoomed ? view[0] : undefined,
    t1: zoomed ? view[1] : undefined,
    text: zoomed ? `${view[0].toFixed(2)} to ${view[1].toFixed(2)} s (zoomed window)` : "the whole log",
  };
}
