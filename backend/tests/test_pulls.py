import io

import numpy as np
import pandas as pd
import pytest

from backend.app import pulls


def dyno_log(hz=100, accel=2.0, with_coast=True, second_pull=True):
    """Idle, a pull (RPM 3000 to 11000 over 20 s, steady roller acceleration), a coast-down, and optionally another pull."""
    t_all, rpm, speed, lam = [], [], [], []
    t = 0.0
    v = 0.0

    def add(duration, rpm_f, dv):
        nonlocal t, v
        for _ in range(int(duration * hz)):
            t_all.append(t)
            rpm.append(rpm_f(t))
            speed.append(v * 3.6)
            lam.append(0.80 + 0.001 * (rpm[-1] - 3000) / 100)
            v = max(v + dv / hz, 0.0)
            t += 1 / hz

    add(3, lambda x: 2500.0, 0.0)
    t0 = t
    add(20, lambda x: 3000 + (x - t0) * 400, accel)  # steady acceleration: power rises as v grows
    if with_coast:
        t1 = t
        add(10, lambda x: 11000 - (x - t1) * 500, -1.0)
    if second_pull:
        t2 = t
        add(15, lambda x: 3000 + (x - t2) * 600, accel * 1.2)
    return pd.DataFrame({"Time": t_all, "rpm": rpm, "vehicleSpeed": speed, "lam1": lam})


def upload(client, df):
    r = client.post("/api/sources", files={"file": ("2025-11-19 10-00-00 plus 0h00m00s t.csv", io.BytesIO(df.to_csv(index=False).encode()), "text/csv")})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_finds_the_pulls_and_ignores_idle_and_coast_down():
    df = dyno_log()
    ranges = pulls.find_pulls(df.Time.to_numpy(), df.rpm.to_numpy())
    assert len(ranges) == 2
    (a, b), (c, d) = ranges
    assert df.Time[a] == pytest.approx(3.0, abs=0.7) and df.Time[b] == pytest.approx(23.0, abs=0.7)
    assert df.rpm[b] - df.rpm[a] > 7500
    assert df.Time[c] > 33  # the coast-down in between is not a pull


def test_a_slow_ramp_below_the_span_is_not_a_pull():
    t = np.arange(0, 30, 0.01)
    rpm = 3000 + t * 100  # 100 rpm/s, under the 150 rpm/s a sweep needs
    assert pulls.find_pulls(t, rpm) == []


def test_power_from_acceleration_matches_the_physics():
    t = np.arange(0, 10, 0.01)
    v = 2.0 * t  # constant 2 m/s^2
    p = pulls.wheel_power(t, v, 200.0)  # kW with 200 kg effective mass: m*v*a
    mid = np.argmin(abs(t - 5))
    assert p[mid] == pytest.approx(200 * 10 * 2 / 1000, rel=0.02)  # 4 kW at 10 m/s
    assert pulls.wheel_power(t, v, None)[mid] == pytest.approx(20, rel=0.02)  # raw m^2/s^3 without a mass


def test_api_pulls_curves_and_peaks(client):
    sid = upload(client, dyno_log())
    r = client.get("/api/pulls", params={"sources": sid, "channels": "lam1", "bin": 200}).json()
    assert [p["n"] for p in r["logs"][sid]["pulls"]] == [1, 2]
    cmp = r["compare"]
    assert cmp["power_unit"] == "index" and len(cmp["curves"]) == 2
    rpm = np.array(cmp["rpm"])
    first = next(c for c in cmp["curves"] if c["n"] == 1)["channels"]
    # lambda rises with rpm in this log; the curve follows it
    lam = np.array([np.nan if x is None else x for x in first["lam1"]])
    assert lam[np.isfinite(lam)][-1] > lam[np.isfinite(lam)][0]
    # constant acceleration: power climbs with speed, so it peaks at the top of the pull
    assert cmp["peaks"][0]["rpm_at_peak_power"] >= 10000
    best = max(p["peak_power"] for p in cmp["peaks"])
    assert best == pytest.approx(100.0)  # normalised so the strongest pull is 100


def test_api_with_mass_gives_kilowatts_and_selection_filters(client):
    sid = upload(client, dyno_log())
    r = client.get("/api/pulls", params={"sources": sid, "mass_kg": 250, "selected": f"{sid}:2"}).json()
    assert r["compare"]["power_unit"] == "kW"
    assert [c["n"] for c in r["compare"]["curves"]] == [2]
    assert r["compare"]["peaks"][0]["peak_power"] > 1.0


def test_logs_without_rpm_are_skipped(client):
    sid = upload(client, dyno_log().drop(columns=["rpm"]))
    r = client.get("/api/pulls", params={"sources": sid}).json()
    assert r["compare"] is None and r["skipped"][0]["reason"] == "no rpm channel"


def test_engine_starts_do_not_count_and_a_gear_change_does_not_split_a_pull():
    hz = 100
    t = np.arange(0, 40, 1 / hz)
    rpm = np.zeros_like(t)
    rpm[(t >= 2) & (t < 4)] = 0 + (t[(t >= 2) & (t < 4)] - 2) * 1800  # cranking: 0 to 3600 in 2 s
    rpm[(t >= 4) & (t < 6)] = 2500
    sweep = (t >= 6) & (t < 26)
    rpm[sweep] = 3000 + (t[sweep] - 6) * 400  # 3000 to 11000
    dip = (t >= 15) & (t < 15.8)
    rpm[dip] = rpm[dip] - 700  # a gear change in the middle
    found = pulls.find_pulls(t, rpm)
    assert len(found) == 1  # the start is ignored, and the dip does not break the sweep in two
    assert t[found[0][0]] == pytest.approx(6.0, abs=0.8)


def test_pull_table_flags_a_free_rev():
    t = np.arange(0, 10, 0.01)
    rpm = 2000 + t * 600
    speed = np.zeros_like(t)  # the roller never moves
    row = pulls.pull_table(t, rpm, speed, [(0, len(t) - 1)])[0]
    assert row["loaded"] is False
    row = pulls.pull_table(t, rpm, t * 8.0, [(0, len(t) - 1)])[0]
    assert row["loaded"] is True
