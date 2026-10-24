"""Event detection: turn a true/false signal into a list of time spans."""

from __future__ import annotations

import numpy as np


def find_events(
    t: np.ndarray, flag: np.ndarray, min_duration_s: float = 0.0, merge_gap_s: float = 0.0
) -> list[dict]:
    """Spans where ``flag`` is true (NaN counts as false).

    Each event runs from the first true sample to the last true sample of the run (so a single
    sample has zero length; its duration is taken as one sample interval). Runs separated by
    less than ``merge_gap_s`` are joined, then runs shorter than ``min_duration_s`` are dropped.
    """
    on = np.nan_to_num(np.asarray(flag, dtype=float)) > 0.5
    if t.size == 0 or not on.any():
        return []
    dt = float(np.median(np.diff(t))) if t.size > 1 else 0.0
    edges = np.diff(np.concatenate([[0], on.astype(np.int8), [0]]))
    starts, ends = np.where(edges == 1)[0], np.where(edges == -1)[0] - 1
    runs = [[float(t[a]), float(t[b]), int(a), int(b)] for a, b in zip(starts, ends)]
    merged: list[list] = []
    for r in runs:
        if merged and r[0] - merged[-1][1] <= merge_gap_s:
            merged[-1][1], merged[-1][3] = r[1], r[3]
        else:
            merged.append(r)
    out = []
    for t_start, t_end, a, b in merged:
        dur = max(t_end - t_start, dt)
        if dur >= min_duration_s:
            out.append({"t_start": t_start, "t_end": t_end, "duration_s": dur, "samples": b - a + 1})
    return out
