import io

import numpy as np
import pandas as pd
import pytest

from backend.app import laps


def circuit(lap_times=(20.0, 30.0, 28.0, 32.0, 10.0), radius=100.0, hz=50, beacon=True, timer=True):
    """A car driving round a circle at a steady speed per lap, so laps, distance and shape are known."""
    rows, t0, dist_lap = [], 0.0, 2 * np.pi * radius
    out = {k: [] for k in ["Time", "vehicleSpeed", "latG", "lapTime", "lastLapTime", "beacon"]}
    last = 0.0
    for lt in lap_times:
        n = int(lt * hz)
        v = dist_lap / lt  # m/s
        for i in range(n):
            tt = i / hz
            out["Time"].append(t0 + tt)
            out["vehicleSpeed"].append(v * 3.6)
            out["latG"].append(v * v / radius / 9.80665)
            out["lapTime"].append(tt)
            out["lastLapTime"].append(last)
            out["beacon"].append(1.0 if i < 3 else 0.0)
        t0 += lt
        last = lt
    df = pd.DataFrame(out)
    if not timer:
        df = df.drop(columns=["lapTime", "lastLapTime"])
    if not beacon:
        df = df.drop(columns=["beacon"])
    return df


def upload(client, df):
    r = client.post("/api/sources", files={"file": ("2025-11-19 10-00-00 plus 0h00m00s t.csv", io.BytesIO(df.to_csv(index=False).encode()), "text/csv")})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_laps_found_from_the_lap_timer(client):
    sid = upload(client, circuit())
    r = client.get(f"/api/sources/{sid}/laps").json()
    assert "lapTime" in r["found_by"]
    # the out-lap and the in-lap have no line crossing at one end, so only the three flying laps count
    assert [round(l["duration_s"], 1) for l in r["laps"]] == [30.0, 28.0, 32.0]
    best = next(l for l in r["laps"] if l["best"])
    assert best["duration_s"] == pytest.approx(28.0, abs=0.1)
    assert r["laps"][0]["delta_best_s"] == pytest.approx(2.0, abs=0.1)
    assert r["laps"][0]["distance_m"] == pytest.approx(2 * np.pi * 100, rel=0.02)


def test_laps_from_beacon_distance_and_manual(client):
    sid = upload(client, circuit(timer=False))
    trig = client.get(f"/api/sources/{sid}/laps", params={"method": "trigger", "channel": "beacon"}).json()
    assert [round(l["duration_s"]) for l in trig["laps"]] == [30, 28, 32]
    dist = client.get(f"/api/sources/{sid}/laps", params={"method": "distance", "length_m": 628.3}).json()
    assert len(dist["laps"]) >= 2
    hand = client.get(f"/api/sources/{sid}/laps", params={"method": "manual", "times": "20,50,78"}).json()
    assert [round(l["duration_s"]) for l in hand["laps"]] == [30, 28]


def test_no_lap_signal_is_explained(client):
    sid = upload(client, circuit(timer=False, beacon=False))
    r = client.get(f"/api/sources/{sid}/laps")
    assert r.status_code == 422 and "lap" in r.json()["detail"].lower()


def test_out_lap_is_not_valid(client):
    sid = upload(client, circuit(lap_times=(30.0, 12.0, 30.0, 29.0, 31.0, 5.0)))
    laps_ = client.get(f"/api/sources/{sid}/laps").json()["laps"]
    assert laps_[0]["valid"] is False and not laps_[0]["best"]
    assert next(l for l in laps_ if l["best"])["duration_s"] == pytest.approx(29.0, abs=0.1)


def test_overlay_delta_against_best_lap(client):
    sid = upload(client, circuit(lap_times=(20.0, 30.0, 28.0, 32.0, 28.0, 5.0)))
    r = client.get(f"/api/sources/{sid}/lapview", params={"channels": "vehicleSpeed", "points": 200}).json()
    assert r["axis"] == "distance" and len(r["x"]) == 200
    by_n = {l["n"]: l for l in r["laps"]}
    ref = r["reference"]
    assert by_n[ref]["delta_s"][-1] == pytest.approx(0.0, abs=0.05)
    other = next(l for n, l in by_n.items() if n != ref and abs(l["duration_s"] - 30) < 1)
    assert other["delta_s"][-1] == pytest.approx(2.0, abs=0.15)  # two seconds slower at the line
    assert other["delta_s"][100] > 0.5  # and already behind halfway round
    time_axis = client.get(f"/api/sources/{sid}/lapview", params={"channels": "vehicleSpeed", "axis": "time"}).json()
    assert time_axis["axis"] == "time" and "delta_s" not in time_axis["laps"][0]


def test_track_shape_from_lateral_g_closes_the_loop(client):
    sid = upload(client, circuit(lap_times=(30.0, 30.0, 30.0)))
    r = client.get(f"/api/sources/{sid}/track", params={"color": "vehicleSpeed"}).json()
    assert r["estimated"] is True and r["source"] == "lateral g"
    x = np.array(r["x"], dtype=float)
    y = np.array(r["y"], dtype=float)
    # a circle of radius 100 m: the width should be about 200 m
    assert (x.max() - x.min()) == pytest.approx(200, rel=0.1)
    assert (y.max() - y.min()) == pytest.approx(200, rel=0.1)
    assert len(r["color"]) == len(r["x"])
    assert len(r["boundaries"]) >= 2


def test_track_uses_gps_when_present(client):
    df = circuit()
    ang = np.cumsum(np.full(len(df), 0.02))
    df["latitude"] = 51.5 + 0.0009 * np.cos(ang)
    df["longitude"] = -2.6 + 0.0014 * np.sin(ang)
    sid = upload(client, df)
    r = client.get(f"/api/sources/{sid}/track").json()
    assert r["source"] == "gps" and r["estimated"] is False


def test_track_without_anything_to_draw_from(client):
    df = circuit().drop(columns=["latG"])
    df["vehicleSpeed"] = 0.0
    sid = upload(client, df.drop(columns=["lapTime", "lastLapTime", "beacon"]))
    r = client.get(f"/api/sources/{sid}/track")
    assert r.status_code == 422


def test_distance_helpers():
    t = np.linspace(0, 10, 101)
    d = laps.cumulative_distance(t, np.full(101, 10.0))
    assert d[-1] == pytest.approx(100.0)
    assert laps.to_mps(np.array([36.0]), "km/h")[0] == pytest.approx(10.0)
    assert laps.to_mps(np.array([10.0]), "m/s")[0] == 10.0
    assert laps.pick_speed(["Rpm", "VehicleSpeed"]) == "VehicleSpeed"
    assert laps.guess_position(["latG", "longG", "gpsLatitude", "gpsLongitude"]) == ("gpsLatitude", "gpsLongitude")
    assert laps.guess_position(["latG", "longG"]) is None


def test_laps_compared_across_logs(client):
    a = upload(client, circuit(lap_times=(20.0, 30.0, 30.0, 5.0)))
    b = upload(client, circuit(lap_times=(20.0, 28.0, 29.0, 5.0)).assign(latG=lambda d: d.latG + 0.001))
    r = client.get("/api/lapcompare", params={"sources": f"{a},{b}", "channels": "vehicleSpeed"}).json()
    assert {l["log"] for l in r["laps"]} == {a, b}
    assert r["best"] == {"log": b, "n": 1}
    ref = next(l for l in r["laps"] if l["log"] == b and l["n"] == 1)
    assert ref["delta_s"][-1] == pytest.approx(0.0, abs=0.05)
    slow = next(l for l in r["laps"] if l["log"] == a and l["n"] == 1)
    assert slow["delta_s"][-1] == pytest.approx(2.0, abs=0.15)  # a different session, two seconds off the best
    pinned = client.get("/api/lapcompare", params={"sources": f"{a},{b}", "channels": "vehicleSpeed", "ref": f"{a}:1", "selected": f"{a}:1,{b}:2"}).json()
    assert [(l["log"], l["n"]) for l in pinned["laps"]] == [(a, 1), (b, 2)]
    assert pinned["reference_log"] == a


def test_compare_skips_logs_without_laps(client):
    a = upload(client, circuit())
    b = upload(client, circuit(timer=False, beacon=False).assign(Time=lambda d: d.Time + 500))
    r = client.get("/api/lapcompare", params={"sources": f"{a},{b}", "channels": "vehicleSpeed"}).json()
    assert {l["log"] for l in r["laps"]} == {a}
    assert r["skipped"] and r["skipped"][0]["id"] == b


def test_lap_metrics_sectors_and_ideal_lap(client):
    a = upload(client, circuit(lap_times=(20.0, 30.0, 28.0, 32.0, 5.0)))
    r = client.get("/api/lapstats", params={"sources": a, "channels": "vehicleSpeed", "sectors": 3}).json()
    assert [l["n"] for l in r["laps"]] == [1, 2, 3]
    one = r["laps"][0]
    assert one["metrics"]["vehicleSpeed"]["max"] == pytest.approx(2 * np.pi * 100 / 30 * 3.6, rel=0.01)
    # steady speed round a circle: each third of a 30 s lap takes 10 s, of a 28 s lap 9.33 s
    assert one["sectors"] == pytest.approx([10.0, 10.0, 10.0], abs=0.15)
    assert sum(r["laps"][1]["sectors"]) == pytest.approx(28.0, abs=0.1)
    assert r["ideal_s"] == pytest.approx(28.0, abs=0.2)  # the 28 s lap is best in every sector
    assert [b["n"] for b in r["best_sectors"]] == [2, 2, 2]


def test_ideal_lap_beats_every_real_lap_when_bests_differ(client):
    import numpy as np
    df = circuit(lap_times=(20.0, 30.0, 30.0, 30.0, 5.0))
    # lap 1: quick first half, slow second; lap 2: the reverse. Same total, so the ideal lap is quicker than either.
    n_lap = int(30.0 * 50)
    v = df["vehicleSpeed"].to_numpy().copy()
    start = int(20.0 * 50)
    for k, fast_first in ((0, True), (1, False)):
        a, b = start + k * n_lap, start + (k + 1) * n_lap
        half = (a + b) // 2
        v[a:half] = v[a:half] * (1.25 if fast_first else 0.8)
        v[half:b] = v[half:b] * (0.8 if fast_first else 1.25)
    df["vehicleSpeed"] = v
    sid = upload(client, df)
    r = client.get("/api/lapstats", params={"sources": sid, "sectors": 2}).json()
    real = min(l["duration_s"] for l in r["laps"] if l["valid"])
    assert r["ideal_s"] < real - 0.5
