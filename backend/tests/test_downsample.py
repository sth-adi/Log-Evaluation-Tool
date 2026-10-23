import numpy as np

from backend.app.downsample import minmax_downsample


def test_small_window_returns_full_resolution():
    t = np.linspace(0, 10, 500)
    y = np.sin(t)
    tt, yy, full = minmax_downsample(t, y, 0, 10, 1000)
    assert full and tt.size == 500


def test_spike_is_preserved_and_size_bounded():
    t = np.linspace(0, 100, 2_000_000)
    y = np.zeros_like(t)
    y[1_234_567] = 50.0
    y[777_777] = -20.0
    tt, yy, full = minmax_downsample(t, y, 0, 100, 800)
    assert not full
    assert tt.size <= 2 * 800 + 2
    assert yy.max() == 50.0 and yy.min() == -20.0
    assert np.all(np.diff(tt) >= 0)


def test_window_restricts_range():
    t = np.linspace(0, 100, 100_000)
    y = np.sin(t)
    tt, yy, _ = minmax_downsample(t, y, 40, 50, 300)
    assert tt.min() >= 39.9 and tt.max() <= 50.1


def test_nan_samples_skipped():
    t = np.arange(10.0)
    y = np.array([1, np.nan, 3, 4, np.nan, 6, 7, 8, 9, 10.0])
    tt, yy, _ = minmax_downsample(t, y, 0, 9, 100)
    assert not np.isnan(yy).any() and tt.size == 8
