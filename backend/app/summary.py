"""Run summaries: one number per log per metric, optionally only while a condition holds.

A metric is a formula (usually just a channel), an aggregate, and an optional "only when" formula,
for example: average of lam1 only when tps1 > 90. Formulas use the same engine as calculated
channels and event rules.
"""

from __future__ import annotations

import numpy as np

AGGS = {
    "max": "Highest",
    "min": "Lowest",
    "mean": "Average",
    "median": "Median",
    "std": "Spread (std dev)",
    "p95": "95th percentile",
    "first": "First value",
    "last": "Last value",
    "integral": "Total (value x time)",
    "seconds": "Seconds the condition holds",
}


def aggregate(t: np.ndarray, v: np.ndarray, where: np.ndarray | None, agg: str) -> float | None:
    """One number from the samples where ``where`` is true (all samples if None). None if nothing qualifies."""
    if agg not in AGGS:
        raise ValueError(f"unknown aggregate {agg!r}")
    keep = np.ones(t.size, dtype=bool) if where is None else np.nan_to_num(where) > 0.5
    dt = float(np.median(np.diff(t))) if t.size > 1 else 0.0
    if agg == "seconds":
        return float(keep.sum() * dt) if keep.any() else 0.0
    ok = keep & np.isfinite(v)
    if not ok.any():
        return None
    x, tt = v[ok], t[ok]
    if agg == "max":
        return float(x.max())
    if agg == "min":
        return float(x.min())
    if agg == "mean":
        return float(x.mean())
    if agg == "median":
        return float(np.median(x))
    if agg == "std":
        return float(x.std())
    if agg == "p95":
        return float(np.percentile(x, 95))
    if agg == "first":
        return float(x[0])
    if agg == "last":
        return float(x[-1])
    # integral: each qualifying sample stands for one sample interval
    return float(x.sum() * dt)
