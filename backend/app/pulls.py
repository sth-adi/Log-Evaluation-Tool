"""Engine pulls: find the sweeps in a dyno or ECU log and compare them against RPM.

A pull is a stretch where engine speed climbs steadily. Plotting a pull against RPM instead of time
is what makes two runs comparable: the same RPM lines up even if one sweep was slower.

Power comes from how fast the roller (or the car) accelerates, the inertia method: with an effective
mass m, power = m * v * dv/dt. Without m the curve is a relative index (the best pull peaks at 100).
It leaves out drag and driveline losses, so read it as a way to compare runs, not an absolute figure.
"""

from __future__ import annotations

import numpy as np

G_SMOOTH_S = 0.8  # speed is smoothed over this long before it is differentiated


def smooth(y: np.ndarray, n: int) -> np.ndarray:
    """Moving average over n samples, with the edges averaged over what exists."""
    if n <= 1 or y.size < 3:
        return y.astype(float)
    k = np.ones(n)
    ok = np.isfinite(y)
    num = np.convolve(np.where(ok, y, 0.0), k, mode="same")
    den = np.convolve(ok.astype(float), k, mode="same")
    return np.where(den > 0, num / np.maximum(den, 1e-9), np.nan)


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Index ranges [a, b) where mask is True."""
    d = np.diff(np.concatenate([[0], mask.astype(int), [0]]))
    return list(zip(np.where(d == 1)[0], np.where(d == -1)[0]))


def find_pulls(
    t: np.ndarray,
    rpm: np.ndarray,
    slope_rpm_s: float = 150.0,
    min_span_rpm: float = 3000.0,
    min_dur_s: float = 3.0,
    gap_s: float = 1.5,
    min_start_rpm: float = 800.0,
) -> list[tuple[int, int]]:
    """Sample ranges (start, end inclusive) where RPM climbs at least ``slope_rpm_s`` for a while.

    Starting the engine (RPM leaping up from nothing) is not a pull, so a sweep must begin above
    ``min_start_rpm``. A dip shorter than ``gap_s`` that does not drop RPM much (a gear change, a
    moment off the throttle) joins the two halves into one pull.
    """
    if t.size < 10:
        return []
    dt = float(np.median(np.diff(t)))
    if dt <= 0:
        return []
    r = np.where(np.isfinite(rpm), rpm, 0.0)
    rs = smooth(r, max(1, int(0.4 / dt)))
    slope = np.gradient(rs, t)
    mask = slope > slope_rpm_s
    # a gear change or a lift for a moment should not split one pull in two
    gap_n = max(1, int(gap_s / dt))
    runs = _runs(mask)
    merged: list[list[int]] = []
    for a, b in runs:
        # rejoin only if the gap is short AND the revs have not fallen away during it
        if merged and a - merged[-1][1] <= gap_n and rs[a] >= 0.85 * rs[merged[-1][1] - 1]:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    out = []
    for a, b in merged:
        b = b - 1
        if t[b] - t[a] >= min_dur_s and rs[b] - rs[a] >= min_span_rpm and rs[a] >= min_start_rpm:
            out.append((int(a), int(b)))
    return out


def wheel_power(t: np.ndarray, speed_mps: np.ndarray, mass_kg: float | None) -> np.ndarray:
    """Power in kW (with an effective mass) or in raw m^2/s^3 (without), from acceleration."""
    dt = float(np.median(np.diff(t))) if t.size > 2 else 0.0
    v = smooth(np.where(np.isfinite(speed_mps), speed_mps, np.nan), max(1, int(G_SMOOTH_S / dt)) if dt > 0 else 1)
    a = np.gradient(v, t)
    p = v * a
    return p * (mass_kg / 1000.0) if mass_kg else p


def pull_table(t: np.ndarray, rpm: np.ndarray, speed_kmh: np.ndarray | None, ranges: list[tuple[int, int]]) -> list[dict]:
    rows = []
    for n, (a, b) in enumerate(ranges, start=1):
        seg = slice(a, b + 1)
        row = {
            "n": n,
            "t_start": float(t[a]),
            "t_end": float(t[b]),
            "duration_s": float(t[b] - t[a]),
            "rpm_start": float(rpm[a]),
            "rpm_end": float(rpm[b]),
            "rpm_peak": float(np.nanmax(rpm[seg])),
        }
        if speed_kmh is not None and np.isfinite(speed_kmh[seg]).any():
            row["speed_start_kmh"] = float(np.nanmin(speed_kmh[seg]))
            row["speed_end_kmh"] = float(np.nanmax(speed_kmh[seg]))
            row["loaded"] = row["speed_end_kmh"] - row["speed_start_kmh"] >= 10.0  # False: revved without moving the roller
        rows.append(row)
    return rows


def bin_pull(rpm: np.ndarray, cols: dict[str, np.ndarray], edges: np.ndarray) -> dict[str, np.ndarray]:
    """Average each column in RPM bins. Bins the pull never reached are NaN."""
    x = np.maximum.accumulate(np.where(np.isfinite(rpm), rpm, 0.0))  # a small wobble must not send a bin backwards
    which = np.digitize(x, edges) - 1
    n = len(edges) - 1
    inside = (which >= 0) & (which < n)
    out = {}
    for name, v in cols.items():
        ok = inside & np.isfinite(v)
        cnt = np.bincount(which[ok], minlength=n)[:n]
        tot = np.bincount(which[ok], weights=v[ok], minlength=n)[:n]
        out[name] = np.where(cnt > 0, tot / np.maximum(cnt, 1), np.nan)
    return out


def compare(runs: list[dict], bin_rpm: float = 100.0, mass_kg: float | None = None) -> dict:
    """Curves against RPM for every pull in every run.

    Each run: key, t, rpm, speed_kmh (or None), cols (channels to plot), ranges, selected (pull numbers).
    """
    picks = []
    for run in runs:
        for n, (a, b) in enumerate(run["ranges"], start=1):
            if n in run["selected"]:
                picks.append((run, n, a, b))
    if not picks:
        raise ValueError("No pulls to compare")
    lo = float(np.floor(min(np.nanmin(r["rpm"][a : b + 1]) for r, _, a, b in picks) / bin_rpm) * bin_rpm)
    hi = float(np.ceil(max(np.nanmax(r["rpm"][a : b + 1]) for r, _, a, b in picks) / bin_rpm) * bin_rpm)
    edges = np.arange(lo, hi + bin_rpm, bin_rpm)
    centres = (edges[:-1] + edges[1:]) / 2
    curves, peaks = [], []
    for run, n, a, b in picks:
        seg = slice(a, b + 1)
        cols = {name: v[seg] for name, v in run["cols"].items()}
        if run["speed_kmh"] is not None:
            p = wheel_power(run["t"], run["speed_kmh"] / 3.6, mass_kg)[seg]
            cols["power"] = p
        binned = bin_pull(run["rpm"][seg], cols, edges)
        if "power" in binned:
            w = centres * 2 * np.pi / 60.0  # rad/s of the engine
            binned["torque"] = np.where(np.isfinite(binned["power"]), binned["power"] * (1000.0 if mass_kg else 1.0) / w, np.nan)
        curves.append({"log": run["key"], "n": n, "curves": binned})
    # no mass given: scale so the strongest pull peaks at 100, torque by the same factor
    unit = "kW" if mass_kg else "index"
    if "power" in curves[0]["curves"] and not mass_kg:
        for key in ("power", "torque"):
            top = max((np.nanmax(c["curves"][key]) for c in curves if np.isfinite(c["curves"][key]).any()), default=0.0)
            if top > 0:
                for c in curves:
                    c["curves"][key] = c["curves"][key] * 100.0 / top
    for c in curves:
        pk = {"log": c["log"], "n": c["n"]}
        reached = c["curves"]["power"] if "power" in c["curves"] else next(iter(c["curves"].values()))
        top_rpm = float(centres[np.isfinite(reached)].max()) if np.isfinite(reached).any() else 0.0
        for key in ("power", "torque"):
            v = c["curves"].get(key)
            if v is not None:
                # torque = power / engine speed is meaningless near idle, so only look in the working range
                v = np.where(centres >= 0.4 * top_rpm, v, np.nan) if key == "torque" else v
            if key == "torque" and v is not None:
                c["curves"]["torque"] = v  # the same masked curve is what gets drawn
            if v is not None and np.isfinite(v).any():
                i = int(np.nanargmax(v))
                pk[f"peak_{key}"] = float(v[i])
                pk[f"rpm_at_peak_{key}"] = float(centres[i])
        peaks.append(pk)
    return {
        "rpm": centres.tolist(),
        "power_unit": unit,
        "peaks": peaks,
        "curves": [
            {"log": c["log"], "n": c["n"], "channels": {k: [None if not np.isfinite(x) else float(x) for x in v] for k, v in c["curves"].items()}}
            for c in curves
        ],
    }
