"""Numeric analysis over a window of one log: statistics, histogram, spectrum, scatter.

All functions take plain numpy arrays (NaN = missing) and return JSON-ready dicts.
"""

from __future__ import annotations

import numpy as np

from .rates import update_points

MAX_FFT_POINTS = 1 << 19
MAX_SCATTER_POINTS = 4000


def _clean(a: np.ndarray) -> np.ndarray:
    a = np.asarray(a, dtype=float)
    return a[np.isfinite(a)]


def stats(y: np.ndarray, t: np.ndarray) -> dict:
    v = _clean(y)
    if v.size == 0:
        return {"count": 0, "missing": int(len(y))}
    p = np.percentile(v, [1, 5, 50, 95, 99])
    ok = np.isfinite(y)
    tt, yy = t[ok], y[ok]
    # time-weighted mean (samples are not always evenly spaced), via the trapezoid rule
    if tt.size > 1 and tt[-1] > tt[0]:
        twm = float(np.trapezoid(yy, tt) / (tt[-1] - tt[0]))
    else:
        twm = float(v.mean())
    i_max, i_min = int(np.argmax(yy)), int(np.argmin(yy))
    return {
        "count": int(v.size),
        "missing": int(len(y) - v.size),
        "min": float(v.min()),
        "t_min": float(tt[i_min]),
        "max": float(v.max()),
        "t_max": float(tt[i_max]),
        "mean": float(v.mean()),
        "mean_time_weighted": twm,
        "std": float(v.std()),
        "p1": float(p[0]),
        "p5": float(p[1]),
        "median": float(p[2]),
        "p95": float(p[3]),
        "p99": float(p[4]),
    }


def histogram(y: np.ndarray, bins: int = 40) -> dict:
    v = _clean(y)
    if v.size == 0:
        return {"edges": [], "counts": [], "total": 0}
    lo, hi = float(v.min()), float(v.max())
    if lo == hi:
        lo, hi = lo - 0.5, hi + 0.5
    counts, edges = np.histogram(v, bins=int(np.clip(bins, 2, 400)), range=(lo, hi))
    return {"edges": edges.tolist(), "counts": counts.tolist(), "total": int(v.size)}


def spectrum(t: np.ndarray, y: np.ndarray, out_points: int = 1500) -> dict:
    """Amplitude spectrum (Hann window, mean removed) of a possibly unevenly sampled signal."""
    ok = np.isfinite(y)
    if ok.sum() < 16:
        raise ValueError("Need at least 16 valid samples for a spectrum")
    t, y = t[ok], y[ok]
    dt = float(np.median(np.diff(t)))
    if dt <= 0:
        raise ValueError("Time is not increasing")
    n = int((t[-1] - t[0]) / dt) + 1
    if n > MAX_FFT_POINTS:
        raise ValueError("Window too long for a spectrum; zoom in first")
    grid = t[0] + dt * np.arange(n)
    held = update_points(y)
    if held is None:
        native_hz = None
        u = np.interp(grid, t, y)
    else:  # a channel read slower than the log's rate: use its real readings, and nothing above half its rate
        native_hz = 1.0 / dt / held[1]
        u = np.interp(grid, t[held[0]], y[held[0]])
    u = u - u.mean()
    w = np.hanning(n)
    amp = 2.0 * np.abs(np.fft.rfft(u * w)) / w.sum()
    freq = np.fft.rfftfreq(n, dt)
    freq, amp = freq[1:], amp[1:]  # drop DC
    if native_hz is not None:
        keep = freq <= native_hz / 2.0
        freq, amp = freq[keep], amp[keep]
    peaks = []
    if amp.size >= 3:
        loc = np.where((amp[1:-1] > amp[:-2]) & (amp[1:-1] >= amp[2:]))[0] + 1
        for i in loc[np.argsort(amp[loc])[::-1][:5]]:
            peaks.append({"freq_hz": float(freq[i]), "amplitude": float(amp[i])})
    if freq.size > out_points:  # keep the peaks visible: max over each bucket
        edges = np.linspace(0, freq.size, out_points + 1).astype(int)
        spans = [(a, b) for a, b in zip(edges[:-1], edges[1:]) if b > a]
        freq = np.array([freq[a:b].mean() for a, b in spans])
        amp = np.array([amp[a:b].max() for a, b in spans])
    return {
        "freq_hz": freq.tolist(),
        "amplitude": amp.tolist(),
        "peaks": peaks,
        "sample_rate_hz": 1.0 / dt,
        "native_hz": native_hz,
        "samples": n,
    }


def scatter(t: np.ndarray, x: np.ndarray, y: np.ndarray, limit: int = MAX_SCATTER_POINTS) -> dict:
    ok = np.isfinite(x) & np.isfinite(y)
    t, x, y = t[ok], x[ok], y[ok]
    n = int(len(t))
    if n > limit:
        idx = np.linspace(0, n - 1, limit).astype(int)
        corr = float(np.corrcoef(x, y)[0, 1]) if x.std() > 0 and y.std() > 0 else None
        t, x, y = t[idx], x[idx], y[idx]
    else:
        corr = float(np.corrcoef(x, y)[0, 1]) if n > 2 and x.std() > 0 and y.std() > 0 else None
    return {"t": t.tolist(), "x": x.tolist(), "y": y.tolist(), "points": n, "correlation": corr}


def _nice_range(v: np.ndarray, lo: float | None, hi: float | None) -> tuple[float, float]:
    a = float(np.min(v)) if lo is None else lo
    b = float(np.max(v)) if hi is None else hi
    if b <= a:
        b = a + 1.0
    return a, b


def heatmap(
    x: np.ndarray,
    y: np.ndarray,
    v: np.ndarray | None,
    nx: int = 40,
    ny: int = 30,
    agg: str = "count",
    xr: tuple[float | None, float | None] = (None, None),
    yr: tuple[float | None, float | None] = (None, None),
    min_count: int = 1,
) -> dict:
    """Samples binned on an x/y grid. Each cell holds a sample count or an aggregate of a third channel.

    agg is count, mean, min, max or std. Cells with fewer than ``min_count`` samples are left empty,
    so a single stray sample does not colour a cell. Rows are y, bottom to top.
    """
    if agg not in ("count", "mean", "min", "max", "std"):
        raise ValueError("aggregate must be count, mean, min, max or std")
    if agg != "count" and v is None:
        raise ValueError("Choose a channel to summarise, or show the number of samples")
    ok = np.isfinite(x) & np.isfinite(y)
    if v is not None and agg != "count":
        ok &= np.isfinite(v)
    if not ok.any():
        return {"xedges": [], "yedges": [], "counts": [], "values": [], "vmin": None, "vmax": None, "total": 0}
    x, y = x[ok], y[ok]
    x0, x1 = _nice_range(x, *xr)
    y0, y1 = _nice_range(y, *yr)
    nx, ny = int(np.clip(nx, 2, 120)), int(np.clip(ny, 2, 120))
    inside = (x >= x0) & (x <= x1) & (y >= y0) & (y <= y1)
    x, y = x[inside], y[inside]
    ix = np.minimum(((x - x0) / (x1 - x0) * nx).astype(int), nx - 1)
    iy = np.minimum(((y - y0) / (y1 - y0) * ny).astype(int), ny - 1)
    flat = iy * nx + ix
    counts = np.bincount(flat, minlength=nx * ny).astype(float)
    if agg == "count":
        vals = counts.copy()
    else:
        w = v[ok][inside]
        s1 = np.bincount(flat, weights=w, minlength=nx * ny)
        with np.errstate(invalid="ignore", divide="ignore"):
            mean = s1 / counts
            if agg == "mean":
                vals = mean
            elif agg == "std":
                s2 = np.bincount(flat, weights=w * w, minlength=nx * ny)
                vals = np.sqrt(np.maximum(s2 / counts - mean * mean, 0.0))
            else:
                vals = np.full(nx * ny, np.nan)
                order = np.argsort(flat, kind="stable")
                f, ww = flat[order], w[order]
                starts = np.flatnonzero(np.r_[True, f[1:] != f[:-1]])
                red = (np.minimum if agg == "min" else np.maximum).reduceat(ww, starts)
                vals[f[starts]] = red
    vals = np.where(counts >= max(min_count, 1), vals, np.nan)
    finite = vals[np.isfinite(vals)]
    return {
        "xedges": np.linspace(x0, x1, nx + 1).tolist(),
        "yedges": np.linspace(y0, y1, ny + 1).tolist(),
        "counts": counts.reshape(ny, nx).astype(int).tolist(),
        "values": [[None if not np.isfinite(c) else float(c) for c in row] for row in vals.reshape(ny, nx)],
        "vmin": float(finite.min()) if finite.size else None,
        "vmax": float(finite.max()) if finite.size else None,
        "total": int(counts.sum()),
    }
