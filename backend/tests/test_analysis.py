import numpy as np
import pytest

from backend.app import analysis


def test_stats_time_weighted_and_extremes():
    t = np.array([0.0, 1.0, 2.0, 10.0])
    y = np.array([0.0, 0.0, 10.0, 10.0])
    s = analysis.stats(y, t)
    assert s["max"] == 10 and s["t_max"] == 2.0 and s["min"] == 0 and s["t_min"] == 0.0
    assert s["mean"] == pytest.approx(5.0)
    assert s["mean_time_weighted"] > 7  # the long stretch at 10 dominates
    assert analysis.stats(np.array([np.nan, np.nan]), np.array([0.0, 1.0]))["count"] == 0


def test_histogram_counts_everything_once():
    y = np.concatenate([np.zeros(50), np.ones(50), [np.nan]])
    h = analysis.histogram(y, 10)
    assert sum(h["counts"]) == 100 and h["total"] == 100 and len(h["edges"]) == 11


def test_spectrum_finds_the_tone_even_when_unevenly_sampled():
    rng = np.random.default_rng(1)
    t = np.sort(rng.uniform(0, 20, 4000))
    y = 3.0 * np.sin(2 * np.pi * 12.5 * t) + 100  # DC offset must not show up
    s = analysis.spectrum(t, y)
    top = s["peaks"][0]
    assert top["freq_hz"] == pytest.approx(12.5, abs=0.3)
    assert top["amplitude"] == pytest.approx(3.0, rel=0.25)
    with pytest.raises(ValueError):
        analysis.spectrum(np.arange(5.0), np.arange(5.0))


def test_scatter_thins_and_reports_correlation():
    t = np.arange(10000.0)
    r = analysis.scatter(t, t, 2 * t + 1)
    assert len(r["x"]) == analysis.MAX_SCATTER_POINTS and r["points"] == 10000
    assert r["correlation"] == pytest.approx(1.0)


def test_heatmap_counts_means_and_extremes():
    rng = np.random.default_rng(1)
    x = rng.uniform(0, 10, 20000)
    y = rng.uniform(0, 4, 20000)
    v = x + 10 * y  # a plane, so each cell's mean is the value at its centre
    h = analysis.heatmap(x, y, v, nx=10, ny=4, agg="mean", xr=(0, 10), yr=(0, 4))
    assert h["total"] == 20000 and np.sum(h["counts"]) == 20000
    assert np.allclose(h["xedges"], np.arange(11)) and np.allclose(h["yedges"], np.arange(5))
    assert h["values"][0][0] == pytest.approx(0.5 + 10 * 0.5, abs=0.3)  # cell x 0-1, y 0-1
    assert h["values"][3][9] == pytest.approx(9.5 + 10 * 3.5, abs=0.3)
    hi = analysis.heatmap(x, y, v, nx=10, ny=4, agg="max", xr=(0, 10), yr=(0, 4))
    lo = analysis.heatmap(x, y, v, nx=10, ny=4, agg="min", xr=(0, 10), yr=(0, 4))
    assert hi["values"][0][0] <= 11.0 and lo["values"][0][0] >= 0.0 and hi["values"][0][0] > lo["values"][0][0]
    assert analysis.heatmap(x, y, v, nx=10, ny=4, agg="std", xr=(0, 10), yr=(0, 4))["values"][0][0] > 0


def test_heatmap_hides_thin_cells_and_validates():
    x = np.array([1.0, 1.1, 5.0])  # two samples in one cell, one lonely sample far away
    y = np.array([1.0, 1.0, 9.0])
    h = analysis.heatmap(x, y, None, nx=5, ny=5, agg="count", min_count=2)
    cells = [c for row in h["values"] for c in row if c is not None]
    assert cells == [2.0]
    with pytest.raises(ValueError):
        analysis.heatmap(x, y, None, agg="mean")
    with pytest.raises(ValueError):
        analysis.heatmap(x, y, None, agg="median")
    assert analysis.heatmap(np.array([np.nan]), np.array([1.0]), None)["total"] == 0
