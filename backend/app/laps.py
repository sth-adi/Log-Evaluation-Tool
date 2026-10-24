"""Laps, distance and track shape for one log.

Everything here takes plain numpy arrays (NaN = missing) and returns JSON-ready dicts, like
analysis.py. A lap is the span between two consecutive lap boundaries, so the out-lap and the
in-lap (partial laps at either end) are never counted.
"""

from __future__ import annotations

import re

import numpy as np

G = 9.80665
SPEED_FIRST = ("vehicleSpeed", "drivenSpeed", "gpsSpeed", "speed")
LAP_AUTO = (("lapTime", "reset"), ("lastLapTime", "change"), ("lapCount", "change"), ("lap", "change"))
LAT_RE = re.compile(r"^(gps)?_?lat(itude)?$", re.I)
LON_RE = re.compile(r"^(gps)?_?lon(g|gitude)?$", re.I)
MAX_POINTS = 3000


def to_mps(v: np.ndarray, unit: str) -> np.ndarray:
    u = (unit or "").lower().replace(" ", "")
    if u in ("m/s", "mps"):
        return v
    if u in ("mph", "mi/h"):
        return v * 0.44704
    return v / 3.6  # km/h is what every logger here uses; assume it when the unit is blank


def pick_speed(names: list[str], good: dict[str, bool] | None = None) -> str | None:
    """Best speed channel to integrate: first of the usual names that has real data."""
    by_lower = {n.lower(): n for n in names}
    for want in SPEED_FIRST:
        n = by_lower.get(want.lower())
        if n and (good is None or good.get(n, True)):
            return n
    return None


def guess_position(names: list[str]) -> tuple[str, str] | None:
    lat = next((n for n in names if LAT_RE.match(n)), None)
    lon = next((n for n in names if LON_RE.match(n)), None)
    return (lat, lon) if lat and lon else None


def cumulative_distance(t: np.ndarray, v_mps: np.ndarray) -> np.ndarray:
    """Metres travelled since the first sample (trapezoid rule; missing speed counts as standing still)."""
    v = np.where(np.isfinite(v_mps), np.maximum(v_mps, 0.0), 0.0)
    if t.size < 2:
        return np.zeros_like(t, dtype=float)
    steps = 0.5 * (v[1:] + v[:-1]) * np.diff(t)
    return np.concatenate([[0.0], np.cumsum(np.maximum(steps, 0.0))])


# --- lap boundaries -------------------------------------------------------------------------


def _reset_times(t: np.ndarray, v: np.ndarray, min_lap_s: float) -> list[float]:
    """Where a running lap timer falls back towards zero."""
    ok = np.isfinite(v)
    tt, vv = t[ok], v[ok]
    if vv.size < 2:
        return []
    hits = np.where((vv[1:] < 0.5 * vv[:-1]) & (vv[:-1] > min_lap_s * 0.5))[0] + 1
    return [float(tt[i]) for i in hits]


def _change_times(t: np.ndarray, v: np.ndarray, rising_only: bool) -> list[float]:
    """Where a last-lap-time or lap-counter channel takes a new value."""
    ok = np.isfinite(v)
    tt, vv = t[ok], v[ok]
    if vv.size < 2:
        return []
    hits = np.where(vv[1:] != vv[:-1])[0] + 1
    if rising_only:
        hits = hits[vv[hits] > 0]
    return [float(tt[i]) for i in hits]


def _crossing_times(t: np.ndarray, v: np.ndarray, level: float) -> list[float]:
    ok = np.isfinite(v)
    tt, vv = t[ok], v[ok]
    if vv.size < 2:
        return []
    hits = np.where((vv[:-1] < level) & (vv[1:] >= level))[0]
    # interpolate to the instant of the crossing, not the next sample
    return [float(tt[i] + (level - vv[i]) / (vv[i + 1] - vv[i]) * (tt[i + 1] - tt[i])) for i in hits]


def _spaced(times: list[float], min_gap: float) -> list[float]:
    out: list[float] = []
    for x in sorted(times):
        if not out or x - out[-1] >= min_gap:
            out.append(x)
    return out


def lap_boundaries(
    t: np.ndarray,
    cols: dict[str, np.ndarray],
    dist: np.ndarray | None,
    method: str = "auto",
    channel: str | None = None,
    threshold: float = 0.5,
    length_m: float | None = None,
    times: list[float] | None = None,
    min_lap_s: float = 5.0,
) -> tuple[list[float], str]:
    """Lap start/finish instants and a plain-words description of how they were found."""
    if method == "auto":
        for name, how in LAP_AUTO:
            if name in cols:
                b = _spaced(_reset_times(t, cols[name], min_lap_s) if how == "reset" else _change_times(t, cols[name], True), min_lap_s)
                if len(b) >= 2:
                    return b, f"the {name} channel"
        raise ValueError(
            "No lap signal found. Pick a lap timer or beacon channel, set a lap length, or add lap times by hand."
        )
    if method == "reset":
        if not channel or channel not in cols:
            raise ValueError("Choose the lap timer channel")
        return _spaced(_reset_times(t, cols[channel], min_lap_s), min_lap_s), f"the {channel} timer"
    if method == "change":
        if not channel or channel not in cols:
            raise ValueError("Choose the lap counter channel")
        return _spaced(_change_times(t, cols[channel], False), min_lap_s), f"the {channel} counter"
    if method == "trigger":
        if not channel or channel not in cols:
            raise ValueError("Choose the beacon channel")
        return _spaced(_crossing_times(t, cols[channel], threshold), min_lap_s), f"{channel} rising through {threshold:g}"
    if method == "distance":
        if dist is None:
            raise ValueError("A speed channel is needed to measure distance")
        if not length_m or length_m <= 0:
            raise ValueError("Enter the lap length in metres")
        k = np.arange(0, int(dist[-1] // length_m) + 1)
        return [float(np.interp(i * length_m, dist, t)) for i in k], f"every {length_m:g} m"
    if method == "manual":
        b = sorted(float(x) for x in (times or []))
        if len(b) < 2:
            raise ValueError("Enter at least two times (start and finish of a lap)")
        return b, "times you entered"
    raise ValueError(f"unknown method {method!r}")


# --- lap table ------------------------------------------------------------------------------


def lap_table(t: np.ndarray, dist: np.ndarray | None, speed_kmh: np.ndarray | None, bounds: list[float]) -> dict:
    laps = []
    for n, (a, b) in enumerate(zip(bounds[:-1], bounds[1:]), start=1):
        if b - a <= 0:
            continue
        m = (t >= a) & (t <= b)
        row = {"n": n, "t_start": a, "t_end": b, "duration_s": b - a}
        if dist is not None:
            row["distance_m"] = float(np.interp(b, t, dist) - np.interp(a, t, dist))
        if speed_kmh is not None and m.any() and np.isfinite(speed_kmh[m]).any():
            row["max_kmh"] = float(np.nanmax(speed_kmh[m]))
            row["avg_kmh"] = float(np.nanmean(speed_kmh[m]))
        laps.append(row)
    if not laps:
        return {"laps": [], "best": None, "median_s": None}
    med = float(np.median([l["duration_s"] for l in laps]))
    for l in laps:
        # an in-lap or out-lap is far from typical; it should not decide "best" or the average
        l["valid"] = 0.7 * med <= l["duration_s"] <= 1.4 * med
    pool = [l for l in laps if l["valid"]] or laps
    best = min(pool, key=lambda l: l["duration_s"])
    for l in laps:
        l["delta_best_s"] = l["duration_s"] - best["duration_s"]
        l["best"] = l is best
    return {"laps": laps, "best": best["n"], "median_s": med}


# --- overlay ---------------------------------------------------------------------------------


def _interp(x: np.ndarray, xp: np.ndarray, fp: np.ndarray) -> np.ndarray:
    ok = np.isfinite(fp) & np.isfinite(xp)
    if ok.sum() < 2:
        return np.full(x.shape, np.nan)
    return np.interp(x, xp[ok], fp[ok], left=np.nan, right=np.nan)


def overlay_runs(runs: list[dict], ref: tuple[str, int], axis: str = "distance", points: int = 600) -> dict:
    """Every chosen lap, from one log or several, on one shared x axis (metres or seconds into the lap).

    ``runs`` holds one dict per log: key, t, dist, cols (the channels to draw) and laps (lap rows).
    Distance is rescaled so each lap ends exactly at the reference lap's length: wheel-speed
    integration drifts a little each lap, and without this the laps would slide apart.
    ``delta_s`` is the time each lap is ahead (-) or behind (+) the reference lap at that point.
    """
    use_dist = axis == "distance"
    by_key = {r["key"]: r for r in runs}
    rrun = by_key.get(ref[0]) or runs[0]
    rlap = next((l for l in rrun["laps"] if l["n"] == ref[1]), None) or rrun["laps"][0]
    if use_dist and any(r["dist"] is None for r in runs):
        raise ValueError("A speed channel is needed for a distance axis")
    span = (
        float(np.interp(rlap["t_end"], rrun["t"], rrun["dist"]) - np.interp(rlap["t_start"], rrun["t"], rrun["dist"]))
        if use_dist
        else rlap["duration_s"]
    )
    if span <= 0:
        raise ValueError("The reference lap has no length")
    grid = np.linspace(0.0, span, int(np.clip(points, 50, 3000)))

    def lap_axes(run: dict, l: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        t, dist = run["t"], run["dist"]
        m = (t >= l["t_start"]) & (t <= l["t_end"])
        tl = t[m] - l["t_start"]
        if not use_dist:
            return m, tl, tl
        d = np.maximum.accumulate(dist[m] - np.interp(l["t_start"], t, dist))
        total = d[-1] if d.size else 0.0
        return m, (d * (span / total) if total > 0 else d), tl

    _, rx, rt = lap_axes(rrun, rlap)
    ref_time_at = _interp(grid, rx, rt) if use_dist else None
    out = []
    for run in runs:
        for l in run["laps"]:
            m, xs, tl = lap_axes(run, l)
            if m.sum() < 2:
                continue
            entry = {"log": run["key"], "n": l["n"], "duration_s": l["duration_s"], "channels": {}}
            for name, v in run["cols"].items():
                entry["channels"][name] = [None if not np.isfinite(x) else float(x) for x in _interp(grid, xs, v[m])]
            if use_dist and ref_time_at is not None:
                entry["delta_s"] = [None if not np.isfinite(x) else float(x) for x in _interp(grid, xs, tl) - ref_time_at]
            out.append(entry)
    return {"axis": axis, "x": grid.tolist(), "reference": rlap["n"], "reference_log": rrun["key"], "laps": out}


def overlay(
    t: np.ndarray,
    dist: np.ndarray | None,
    cols: dict[str, np.ndarray],
    laps: list[dict],
    ref_n: int,
    axis: str = "distance",
    points: int = 600,
) -> dict:
    """One log's laps; see overlay_runs."""
    return overlay_runs([{"key": "", "t": t, "dist": dist, "cols": cols, "laps": laps}], ("", ref_n), axis, points)


# --- track shape -----------------------------------------------------------------------------


def _valid_course(c: np.ndarray) -> bool:
    ok = np.isfinite(c)
    return bool(ok.sum() > 10 and (c[ok] >= 0).all() and (c[ok] <= 360).all() and np.nanstd(c[ok]) > 1.0)


def track_path(
    t: np.ndarray,
    speed_mps: np.ndarray | None,
    lat: np.ndarray | None = None,
    lon: np.ndarray | None = None,
    course_deg: np.ndarray | None = None,
    lat_g: np.ndarray | None = None,
    mirror: bool = False,
) -> dict:
    """Plan view of the run in metres.

    Real GPS position is used when the log has it. Otherwise the path is dead-reckoned from speed
    plus heading (GPS course if present, else turning rate from lateral g). That keeps the shape of
    the track but drifts, so ``estimated`` is set and the screen says so.
    """
    if lat is not None and lon is not None:
        ok = np.isfinite(lat) & np.isfinite(lon) & (np.abs(lat) > 1e-6) & (np.abs(lat) <= 90) & (np.abs(lon) <= 180)
        if ok.sum() > 10:
            la0, lo0 = float(np.median(lat[ok])), float(np.median(lon[ok]))
            x = np.where(ok, np.radians(lon - lo0) * 6371000.0 * np.cos(np.radians(la0)), np.nan)
            y = np.where(ok, np.radians(lat - la0) * 6371000.0, np.nan)
            return _finish(t, x, y, "gps")
    if speed_mps is None:
        raise ValueError("No GPS position and no speed channel, so there is nothing to draw")
    v = np.where(np.isfinite(speed_mps), np.maximum(speed_mps, 0.0), 0.0)
    dt = np.diff(t, prepend=t[0])
    if course_deg is not None and _valid_course(course_deg):
        h = np.radians(pd_ffill(course_deg))
        x = np.cumsum(v * np.sin(h) * dt)
        y = np.cumsum(v * np.cos(h) * dt)
        return _finish(t, x, y, "course")
    if lat_g is not None and np.isfinite(lat_g).sum() > 10:
        a = np.where(np.isfinite(lat_g), lat_g, 0.0) * G * (-1.0 if mirror else 1.0)
        rate = np.where(v > 2.0, a / np.maximum(v, 2.0), 0.0)  # rad/s, ignored when nearly stopped
        h = np.cumsum(rate * dt)
        x = np.cumsum(v * np.sin(h) * dt)
        y = np.cumsum(v * np.cos(h) * dt)
        return _finish(t, x, y, "lateral g")
    raise ValueError("The log has no GPS position, GPS course or lateral g to build a track from")


def pd_ffill(a: np.ndarray) -> np.ndarray:
    a = a.astype(float).copy()
    ok = np.isfinite(a)
    if not ok.any():
        return np.zeros_like(a)
    idx = np.where(ok, np.arange(a.size), 0)
    np.maximum.accumulate(idx, out=idx)
    out = a[idx]
    out[: np.argmax(ok)] = a[ok][0]
    return out


def _finish(t: np.ndarray, x: np.ndarray, y: np.ndarray, source: str) -> dict:
    n = t.size
    idx = np.linspace(0, n - 1, min(n, MAX_POINTS)).astype(int)
    return {
        "source": source,
        "estimated": source != "gps",
        "index": idx.tolist(),
        "t": t[idx].tolist(),
        "x": [None if not np.isfinite(v) else float(v) for v in x[idx]],
        "y": [None if not np.isfinite(v) else float(v) for v in y[idx]],
    }
