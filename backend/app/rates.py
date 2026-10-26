"""Real update rates of channels that were put on a faster common time base.

A log file has one row per sample, but the channels in it are not all measured that often.
Life Racing's export, CAN logs and MDF files all hold a slow channel's last value until its
next reading arrives, so the file shows a staircase. Calculus and spectra on the staircase are
wrong, so the tools find the readings that really arrived and work from those.

A reading is seen where the value changes. A channel that is steady for a while looks the same
as a slow one, so the rate is an estimate. The gap between readings is taken from the lower
quartile of the spacing between changes: a repeated value by chance only makes a gap longer.
"""

from __future__ import annotations

import numpy as np

MIN_CHANGES = 20  # fewer changes than this and the channel is too steady to tell
MIN_HOLD = 2.0  # updating every sample or nearly so is not "held"
STEADY_GAP = 3.0  # a stretch this many times the hold period long is steady, not one long ramp


def update_points(x: np.ndarray) -> tuple[np.ndarray, float] | None:
    """Indices of the readings that arrived, and the hold period in samples; None if not held."""
    x = np.asarray(x, dtype=float)
    if x.size < 2:
        return None
    prev = np.concatenate([[np.nan], x[:-1]])
    changed = np.flatnonzero(~np.isclose(x, prev, rtol=0, atol=0, equal_nan=True))
    if changed.size < MIN_CHANGES:
        return None
    hold = float(np.percentile(np.diff(changed), 25))
    if hold < MIN_HOLD:
        return None
    idx = changed
    # a value that sat unchanged for much longer than one hold period was steady: keep it flat
    # up to just before the next change instead of ramping across the whole stretch
    gaps = np.diff(idx)
    long = np.flatnonzero(gaps > STEADY_GAP * hold)
    if long.size:
        idx = np.unique(np.concatenate([idx, idx[long + 1] - 1]))
    return idx, hold


def native_rate_hz(x: np.ndarray, raster_hz: float) -> float | None:
    """Estimated readings per second, or None if the channel updates at the log's own rate
    or is too steady to tell."""
    found = update_points(x)
    if found is None or raster_hz <= 0:
        return None
    return round(raster_hz / found[1], 2)


def reconstruct(t: np.ndarray, x: np.ndarray) -> np.ndarray:
    """The channel as a line through its real readings, evaluated at every sample time.
    A channel that is not held is returned as it is."""
    found = update_points(x)
    if found is None:
        return np.asarray(x, dtype=float)
    idx = found[0]
    return np.interp(t, t[idx], np.asarray(x, dtype=float)[idx])
