"""Min/max bucket downsampling for plotting huge signals.

For a visible window we split time into ``buckets`` equal slices and keep the
minimum and maximum sample of each slice (in time order). That preserves spikes
and dropouts that plain striding would hide, with at most 2 * buckets points.
"""

from __future__ import annotations

import numpy as np


def minmax_downsample(
    t: np.ndarray, y: np.ndarray, t0: float, t1: float, buckets: int
) -> tuple[np.ndarray, np.ndarray, bool]:
    """Return (t, y, is_full_resolution) restricted to [t0, t1]."""
    ok = ~np.isnan(y)
    t, y = t[ok], y[ok]
    lo = int(np.searchsorted(t, t0, side="left"))
    hi = int(np.searchsorted(t, t1, side="right"))
    # include one sample either side so lines run off the edges of the window
    lo, hi = max(lo - 1, 0), min(hi + 1, t.size)
    t, y = t[lo:hi], y[lo:hi]

    if t.size <= 2 * buckets or buckets < 1:
        return t, y, True

    edges = np.linspace(t[0], t[-1], buckets + 1)
    idx = np.searchsorted(t, edges, side="left")
    idx[-1] = t.size
    starts = idx[:-1]
    ends = idx[1:]
    nonempty = ends > starts

    keep: list[int] = []
    for s, e in zip(starts[nonempty], ends[nonempty]):
        seg = y[s:e]
        i_min = s + int(np.argmin(seg))
        i_max = s + int(np.argmax(seg))
        if i_min == i_max:
            keep.append(i_min)
        elif i_min < i_max:
            keep.extend((i_min, i_max))
        else:
            keep.extend((i_max, i_min))
    sel = np.asarray(keep, dtype=int)
    return t[sel], y[sel], False
