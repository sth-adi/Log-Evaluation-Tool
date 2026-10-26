import numpy as np

from backend.app import analysis, derived, rates

RASTER = 250.0
T = np.arange(0, 20, 1 / RASTER)


def held(signal, hz):
    """The signal read ``hz`` times a second and held on the 250 Hz raster."""
    step = int(RASTER / hz)
    read = np.arange(len(T)) // step * step
    return signal(T)[read]


def test_a_channel_read_at_a_tenth_of_the_rate_is_found():
    x = held(lambda t: 3000 + 2000 * np.sin(t), 25)
    assert rates.native_rate_hz(x, RASTER) == 25.0


def test_a_channel_at_the_full_rate_is_not_held():
    x = 3000 + 2000 * np.sin(T) + np.random.default_rng(0).normal(0, 5, len(T))
    assert rates.native_rate_hz(x, RASTER) is None


def test_a_steady_channel_is_left_alone():
    assert rates.native_rate_hz(np.full(len(T), 90.0), RASTER) is None


def test_repeated_values_by_chance_do_not_halve_the_rate():
    rng = np.random.default_rng(1)
    x = held(lambda t: np.round(rng.normal(0, 1, len(t))), 50)  # coarse values repeat now and then
    assert rates.native_rate_hz(x, RASTER) == 50.0


def test_derivative_of_a_held_ramp_is_the_ramp_slope_not_spikes():
    x = held(lambda t: 100 * t, 25)  # true slope 100 per second
    d = derived.evaluate("deriv(x)", {"x": x}, T)
    mid = d[250:-250]
    assert abs(np.median(mid) - 100) < 1
    assert np.max(np.abs(mid - 100)) < 5  # steps would give 0 between readings and ~2500 at each one


def test_spectrum_stops_at_half_the_channels_real_rate():
    x = held(lambda t: np.sin(2 * np.pi * 3 * t), 25)
    s = analysis.spectrum(T, x)
    assert abs(s["native_hz"] - 25.0) < 1e-6
    assert max(s["freq_hz"]) <= 12.5
    assert abs(s["peaks"][0]["freq_hz"] - 3) < 0.2


def test_spectrum_of_a_full_rate_channel_is_not_capped():
    s = analysis.spectrum(T, np.sin(2 * np.pi * 3 * T))
    assert s["native_hz"] is None
    assert max(s["freq_hz"]) > 100
