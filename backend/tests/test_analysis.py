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
