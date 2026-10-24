import numpy as np

from backend.app.events import find_events

T = np.arange(0, 10, 0.1)


def flag(*spans):
    f = np.zeros(T.size)
    for a, b in spans:
        f[(T >= a) & (T <= b)] = 1
    return f


def test_finds_separate_spans():
    ev = find_events(T, flag((1, 2), (5, 5.5)))
    assert [(round(e["t_start"], 1), round(e["t_end"], 1)) for e in ev] == [(1.0, 2.0), (5.0, 5.5)]
    assert ev[0]["duration_s"] == 1.0 or abs(ev[0]["duration_s"] - 1.0) < 1e-9


def test_min_duration_drops_blips_and_merge_joins_dropouts():
    f = flag((1, 3), (3.3, 5), (8, 8))
    assert len(find_events(T, f)) == 3
    assert len(find_events(T, f, min_duration_s=0.5)) == 2
    joined = find_events(T, f, min_duration_s=0.5, merge_gap_s=0.5)
    assert len(joined) == 1 and abs(joined[0]["t_end"] - 5.0) < 1e-9


def test_nan_is_false_and_edges_work():
    f = flag((0, 0.5), (9.5, 9.9))
    f[3] = np.nan
    ev = find_events(T, f)
    assert ev[0]["t_start"] == 0 and abs(ev[-1]["t_end"] - 9.9) < 1e-9
    assert find_events(T, np.zeros(T.size)) == []
