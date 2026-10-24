import numpy as np
import pytest

from backend.app.derived import FormulaError, evaluate, referenced_names

T = np.arange(0, 10, 0.1)
COLS = {"rpm": np.full(T.size, 6000.0), "v": T * 2.0, "odd name": T}


def ev(expr):
    return evaluate(expr, COLS, T)


def test_arithmetic_and_constants():
    assert ev("rpm * 2 * pi / 60")[0] == pytest.approx(6000 * 2 * np.pi / 60)
    assert ev("t")[5] == pytest.approx(0.5)
    assert ev("3")[0] == 3 and ev("3").shape == T.shape


def test_calculus_and_smoothing():
    assert np.allclose(ev("deriv(v)"), 2.0)
    assert ev("integ(v)")[-1] == pytest.approx(T[-1] ** 2, rel=1e-6)
    noisy = {"x": np.where(np.arange(T.size) % 2, 1.0, -1.0)}
    assert abs(evaluate("smooth(x, 0.4)", noisy, T)[10]) < 0.5


def test_conditions_and_odd_channel_names():
    assert ev("where(v > 10, 1, 0)").sum() == (COLS["v"] > 10).sum()
    assert ev('ch("odd name") + 1')[0] == 1
    assert ev("(v > 2) and (v < 4)").sum() == ((COLS["v"] > 2) & (COLS["v"] < 4)).sum()


def test_division_by_zero_becomes_nan_not_error():
    assert np.isnan(ev("v / 0")[1:]).all() or np.isnan(ev("v / (v - v)")).all()


@pytest.mark.parametrize(
    "bad",
    ["", "rpm +", "nope + 1", "__import__('os')", "rpm.real", "open('x')", "rpm[0]", "rpm ** 999",
     "lambda: 1", "[1, 2]", "smooth(rpm)", "pi()", "smooth"],
)
def test_rejects_unsafe_or_invalid(bad):
    with pytest.raises(FormulaError):
        ev(bad)


def test_referenced_names():
    assert {"rpm", "odd name"} <= referenced_names('smooth(rpm, 1) + ch("odd name")')
