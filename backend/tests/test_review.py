import numpy as np
import pytest

from backend.app import review
from backend.app.review import Log

RATE = 250
DUR = 80


def make_log(seed, moving_at=(10, 16, 22, 28, 34, 40, 46, 52), standing_at=(3, 6), dropped=(), label=None, extra=None):
    """A log with a request flag that cuts `ign` 20 ms later, except when the car is standing still."""
    rng = np.random.default_rng(seed)
    t = np.arange(DUR * RATE) / RATE
    speed = np.where(t < 8, 0.0, 40 + 30 * np.sin(t / 3))  # stands still for the first 8 s, then drives
    rpm = 2500 + 1500 * np.sin(t / 5) + rng.normal(0, 20, t.size)
    req = np.zeros(t.size)
    ign = 10 + rng.normal(0, 0.05, t.size)
    for at in (*standing_at, *moving_at):
        i = int(at * RATE)
        req[i : i + int(0.15 * RATE)] = 1
        if at not in standing_at and at not in dropped:
            ign[i + 5 : i + int(0.3 * RATE)] = 0  # the response, 20 ms later
    cols = {
        "rpm": rpm,
        "vehicleSpeed": speed,
        "req": req,
        "ign": ign,
        "temp": 70 + t * 0.1 + rng.normal(0, 0.2, t.size),
        "vbat": 13 + rng.normal(0, 0.05, t.size),
    }
    cols.update(extra or {})
    return Log(id=f"l{seed}", label=label or f"2025-11-19 11-0{seed}-00 run", t=t, cols=cols, meta={"vehicleSpeed": {"unit": "km/h"}})


def kinds(result, kind):
    return [f for f in result["findings"] if f["kind"] == kind]


# --- links ------------------------------------------------------------------------------------


def test_a_request_that_is_usually_answered_is_found_and_the_misses_are_flagged():
    logs = [make_log(i) for i in range(1, 4)]
    links = kinds(review.evaluate(logs), "link")
    assert len(links) == 1
    f = links[0]
    assert f["channels"][0] == "req" and "ign" in f["channels"]
    assert f["count"] == 6  # the two standing requests in each of three logs
    assert f["evidence"]["followed"] == 24 and f["evidence"]["events"] == 30


def test_the_condition_the_misses_share_is_named():
    f = kinds(review.evaluate([make_log(i) for i in range(1, 4)]), "link")[0]
    assert "vehicleSpeed below" in f["detail"] and "km/h" in f["detail"]
    assert "none of the 24 hits did" in f["detail"]
    assert f["severity"] == "low"  # every miss fits the pattern: standing still is normal


def test_a_miss_that_does_not_fit_the_condition_is_the_one_to_look_at():
    # one request while driving gets no answer, as well as the two per log while standing
    logs = [make_log(1, dropped=(34,), moving_at=(10, 16, 22, 28, 34, 40, 46, 52)), make_log(2), make_log(3), make_log(4)]
    f = kinds(review.evaluate(logs), "link")[0]
    assert f["severity"] == "medium"
    assert f["occurrences"][0]["fits"] is False  # listed first
    assert f["occurrences"][0]["log_id"] == "l1" and abs(f["occurrences"][0]["t0"] - 34) < 0.1
    assert "does not fit" in f["detail"]


def test_a_link_that_always_holds_raises_nothing():
    logs = [make_log(i, standing_at=()) for i in range(1, 4)]
    assert kinds(review.evaluate(logs), "link") == []


def test_unrelated_channels_make_no_link():
    rng = np.random.default_rng(9)
    logs = []
    for i in range(1, 4):
        lg = make_log(i, standing_at=(), moving_at=())
        lg.cols["flag"] = (rng.random(lg.n) < 0.0005).astype(float)  # fires now and then, means nothing
        logs.append(lg)
    assert kinds(review.evaluate(logs), "link") == []


def test_a_coarse_measurement_is_not_a_switch():
    # a steering angle logged in steps of 0.5 degrees changes often and happens to line up with cuts
    logs = []
    for i in range(1, 4):
        lg = make_log(i)
        lg.cols["swa"] = np.where(lg.cols["req"] > 0, -25.5, 0.0)  # two levels, not whole numbers
        logs.append(lg)
    triggers = {l["channels"][0] for l in kinds(review.evaluate(logs), "link")}
    assert "swa" not in triggers


def test_two_flags_that_fire_together_are_one_finding():
    logs = []
    for i in range(1, 4):
        lg = make_log(i)
        lg.cols["req_state"] = np.roll(lg.cols["req"], 1)  # the same event, one sample later
        logs.append(lg)
    links = kinds(review.evaluate(logs), "link")
    assert len(links) == 1
    assert links[0]["channels"][0] in ("req", "req_state")


# --- the ECU's own fault channels ---------------------------------------------------------------


def _with_flag(values, running=True):
    lg = make_log(1, standing_at=(), moving_at=())
    flag = np.zeros(lg.n)
    for a, b in values:
        flag[int(a * RATE) : int(b * RATE)] = 1
    lg.cols["limpMode"] = flag
    lg.meta["limpMode"] = {"states": {"0": "OFF", "1": "ON"}}
    if not running:
        lg.cols["rpm"] = np.zeros(lg.n)
    return lg


def test_a_fault_while_the_engine_runs_is_reported():
    out = review.evaluate([_with_flag([(20, 22)]), make_log(2, standing_at=(), moving_at=())])
    f = kinds(out, "report")[0]
    assert f["severity"] == "high" and "ON" in f["title"] and f["count"] == 1


def test_a_fault_while_the_engine_is_stopped_is_not():
    assert kinds(review.evaluate([_with_flag([(20, 22)], running=False)]), "report") == []


def test_a_state_that_is_on_all_the_time_is_a_normal_condition_not_an_alarm():
    out = review.evaluate([_with_flag([(0, 70)]), _with_flag([(0, 65)])])  # off only briefly at the end
    f = kinds(out, "report")[0]
    assert f["severity"] == "low" and "probably how this ECU" in f["detail"]


def test_a_failure_counter_that_counts_up_is_reported():
    lg = make_log(1, standing_at=(), moving_at=())
    count = np.zeros(lg.n)
    count[int(30 * RATE) :] = 1
    count[int(50 * RATE) :] = 2
    lg.cols["gearCutFailCount"] = count
    f = kinds(review.evaluate([lg]), "report")[0]
    assert f["count"] == 2 and f["severity"] == "high"


def test_an_analog_error_signal_is_not_a_fault_counter():
    lg = make_log(1, standing_at=(), moving_at=())
    lg.cols["idleError"] = np.sin(lg.t) * 300  # a control error, not a count of faults
    assert kinds(review.evaluate([lg]), "report") == []


# --- stuck sensors, unused channels, dropouts ----------------------------------------------------


def _log_with(seed, values):
    lg = make_log(seed, standing_at=(), moving_at=())
    lg.cols["oilP"] = values(lg)
    return lg


def test_a_sensor_that_moves_elsewhere_but_is_flat_in_one_run_is_stuck():
    rng = np.random.default_rng(1)
    moving = lambda lg: 300 + 50 * np.sin(lg.t) + rng.normal(0, 1, lg.n)
    flat = lambda lg: np.full(lg.n, 312.0)
    out = review.evaluate([_log_with(1, moving), _log_with(2, moving), _log_with(3, flat)])
    f = kinds(out, "stuck")[0]
    assert f["channels"] == ["oilP"] and f["count"] == 1 and f["occurrences"][0]["log_id"] == "l3"


def test_a_channel_that_never_moves_anywhere_is_unused_not_stuck():
    flat = lambda lg: np.full(lg.n, 1013.0)
    out = review.evaluate([_log_with(1, flat), _log_with(2, flat)])
    assert kinds(out, "stuck") == []
    assert "oilP" in kinds(out, "unused")[0]["channels"]


def test_a_channel_that_goes_blank_while_the_others_log_is_a_dropout():
    lg = _log_with(1, lambda l: 300 + 50 * np.sin(l.t))
    lg.cols["oilP"][int(20 * RATE) : int(22 * RATE)] = np.nan
    f = kinds(review.evaluate([lg]), "dropout")[0]
    assert f["channels"] == ["oilP"] and 1.9 < float(f["occurrences"][0]["note"].split()[0]) < 2.1


def test_a_jump_in_time_is_reported_as_missing_samples():
    lg = make_log(1, standing_at=(), moving_at=())
    keep = np.ones(lg.n, dtype=bool)
    keep[int(30 * RATE) : int(33 * RATE)] = False
    lg = Log(id=lg.id, label=lg.label, t=lg.t[keep], cols={k: v[keep] for k, v in lg.cols.items()}, meta=lg.meta)
    f = kinds(review.evaluate([lg]), "gap")[0]
    assert "missing" in f["title"] and "3.0" in f["occurrences"][0]["note"]


# --- drift: reading differently than before, at the same load -------------------------------------


def _drive(seed, start, shift=0.0, spread=(2000, 6000), label_time=None):
    """A log where `pressure` depends on rpm (and so on load), plus `shift` if something changed."""
    rng = np.random.default_rng(seed)
    t = np.arange(60 * RATE) / RATE
    rpm = spread[0] + (spread[1] - spread[0]) * (0.5 + 0.5 * np.sin(t / 4 + seed))
    thr = np.full(t.size, 80.0)
    cols = {
        "rpm": rpm,
        "tps1": thr,
        "pressure": 200 + 0.02 * rpm + shift + rng.normal(0, 1.0, t.size),
        "distance": np.cumsum(rpm) / 1e6 + (seed - 1) * 5,  # climbs in every run
        "oilTemp": 60 + 0.3 * t + shift * 0.0 + rng.normal(0, 0.3, t.size),  # warms up the same way each time
    }
    return Log(id=f"d{seed}", label=f"run {seed}", t=t, cols=cols, meta={"pressure": {"unit": "kPa"}, "oilTemp": {"unit": "°C"}}, started_at=start)


def test_a_channel_that_reads_higher_at_the_same_load_is_flagged():
    logs = [_drive(1, "2025-11-19T11:00:00"), _drive(2, "2025-11-19T11:10:00", shift=25)]
    f = [f for f in review.evaluate(logs)["findings"] if f["kind"] == "drift"]
    assert [x["channels"] for x in f] == [["pressure"]]
    assert "higher" in f[0]["title"] and f[0]["occurrences"][0]["log_id"] == "d2"
    assert f[0]["severity"] == "medium"


def test_running_at_a_different_load_is_not_drift():
    # the second run only visits higher rpm, where `pressure` is naturally higher
    logs = [_drive(1, "2025-11-19T11:00:00"), _drive(2, "2025-11-19T11:10:00", spread=(3500, 6000))]
    assert [f for f in review.evaluate(logs)["findings"] if f["kind"] == "drift"] == []


def test_a_distance_or_timer_that_only_climbs_is_not_drift():
    logs = [_drive(1, "2025-11-19T11:00:00"), _drive(2, "2025-11-19T11:10:00")]
    assert [f for f in review.evaluate(logs)["findings"] if f["kind"] == "drift"] == []


def test_the_order_is_the_order_the_runs_happened_not_the_order_they_were_opened():
    later = _drive(2, "2025-11-19T11:10:00", shift=25)
    earlier = _drive(1, "2025-11-19T11:00:00")
    f = [f for f in review.evaluate([later, earlier])["findings"] if f["kind"] == "drift"][0]
    assert f["occurrences"][0]["log_id"] == "d2" and "higher" in f["title"]


def test_a_temperature_shift_says_that_warmer_starts_explain_it():
    logs = [_drive(1, "2025-11-19T11:00:00"), _drive(2, "2025-11-19T11:10:00")]
    for l in logs[1:]:
        l.cols["oilTemp"] = l.cols["oilTemp"] + 15  # the second run started warmer
    f = [f for f in review.evaluate(logs)["findings"] if f["kind"] == "drift"][0]
    assert f["channels"] == ["oilTemp"] and "start warmer" in f["detail"]


def test_a_tiny_move_in_a_tightly_regulated_channel_is_not_a_change():
    logs = [_drive(1, "2025-11-19T11:00:00"), _drive(2, "2025-11-19T11:10:00")]
    for i, l in enumerate(logs):
        l.cols["fuelPressure"] = 4000 + 0.3 * np.random.default_rng(i).normal(0, 1, l.n) + (6 if i else 0)  # 0.15% shift
    assert [f for f in review.evaluate(logs)["findings"] if f["kind"] == "drift" and f["channels"] == ["fuelPressure"]] == []


def test_a_timer_that_updates_in_a_few_steps_is_still_an_accumulator():
    logs = [_drive(1, "2025-11-19T11:00:00"), _drive(2, "2025-11-19T11:10:00")]
    for i, l in enumerate(logs):
        l.cols["onLoadTime"] = np.minimum(np.arange(l.n) // 3000, 9) * (3 + 7 * i)  # steps up, never down
    assert [f for f in review.evaluate(logs)["findings"] if f["kind"] == "drift" and f["channels"] == ["onLoadTime"]] == []


def test_one_log_has_nothing_to_be_compared_with():
    assert [f for f in review.evaluate([_drive(1, "2025-11-19T11:00:00")])["findings"] if f["kind"] == "drift"] == []


# --- limits -------------------------------------------------------------------------------------


def test_a_limit_the_user_set_is_checked_while_the_engine_runs():
    lg = make_log(1, standing_at=(), moving_at=())
    limit = {"id": "l1", "channel": "temp", "op": ">", "value": 75, "seconds": 2, "severity": "high", "message": "Too hot", "running_only": True}
    f = kinds(review.evaluate([lg], [limit]), "limit")[0]
    assert f["title"] == "Too hot" and f["severity"] == "high" and f["count"] == 1
    assert float(f["occurrences"][0]["note"].split()[-1]) > 75


def test_a_limit_shorter_than_its_time_is_ignored():
    lg = make_log(1, standing_at=(), moving_at=())
    lg.cols["temp"][int(10 * RATE) : int(10.5 * RATE)] = 200  # half a second over
    limit = {"id": "l1", "channel": "temp", "op": ">", "value": 150, "seconds": 2}
    assert kinds(review.evaluate([lg], [limit]), "limit") == []


def test_a_limit_on_a_channel_nobody_has_says_so():
    limit = {"id": "l1", "channel": "nope", "op": ">", "value": 1, "seconds": 0}
    out = review.evaluate([make_log(1)], [limit])
    assert any("nope" in n for n in out["notes"])


def test_limits_are_validated_and_kept(tmp_path, monkeypatch):
    monkeypatch.setenv("LET_DATA_DIR", str(tmp_path))
    saved = review.set_limits([{"channel": "eot", "op": ">", "value": "120", "seconds": "3"}])
    assert saved[0]["value"] == 120.0 and review.limits() == saved
    for bad in ({"channel": "", "op": ">", "value": 1}, {"channel": "x", "op": "=", "value": 1}, {"channel": "x", "op": ">", "value": "abc"}):
        with pytest.raises(review.LimitError):
            review.set_limits([bad])
    assert review.limits() == saved  # a rejected edit leaves the saved ones alone


def test_findings_can_be_marked_normal_and_brought_back(tmp_path, monkeypatch):
    monkeypatch.setenv("LET_DATA_DIR", str(tmp_path))
    review.mute("link:req=1:ign")
    review.mute("link:req=1:ign")
    assert review.muted() == ["link:req=1:ign"]
    review.unmute("link:req=1:ign")
    assert review.muted() == []


def test_no_logs_says_so():
    out = review.evaluate([])
    assert out["findings"] == [] and out["notes"]


# --- the endpoints ------------------------------------------------------------------------------


def _upload(client, lg):
    import io

    import pandas as pd

    df = pd.DataFrame({"time_s": lg.t, **lg.cols})
    r = client.post("/api/sources", files={"file": ("log.csv", io.BytesIO(df.to_csv(index=False).encode()), "text/csv")})
    assert r.status_code == 200, r.text
    return r.json()


def test_the_review_endpoint_finds_mutes_and_restores(client):
    for i in range(1, 4):
        _upload(client, make_log(i))
    body = client.get("/api/review").json()
    link = next(f for f in body["findings"] if f["kind"] == "link")
    assert body["checked"]["logs"] == 3 and link["count"] == 6

    after = client.post("/api/review/mute", params={"key": link["key"]}).json()
    assert link["key"] not in [f["key"] for f in after["findings"]]
    assert link["key"] in [f["key"] for f in after["muted"]]

    back = client.delete("/api/review/mute", params={"key": link["key"]}).json()
    assert link["key"] in [f["key"] for f in back["findings"]] and back["muted"] == []


def test_limits_through_the_endpoint(client):
    _upload(client, make_log(1))
    r = client.put("/api/review/limits", json={"limits": [{"channel": "temp", "op": ">", "value": 75, "seconds": 2, "message": "Too hot"}]})
    assert r.status_code == 200
    assert any(f["title"] == "Too hot" for f in r.json()["findings"])
    assert r.json()["limits"][0]["channel"] == "temp"
    bad = client.put("/api/review/limits", json={"limits": [{"channel": "temp", "op": "~", "value": 1}]})
    assert bad.status_code == 422 and "above or below" in bad.json()["detail"]
    assert client.get("/api/review").json()["limits"][0]["value"] == 75.0  # the bad edit changed nothing


def test_the_result_follows_the_open_logs(client):
    first = _upload(client, make_log(1))
    assert client.get("/api/review").json()["checked"]["logs"] == 1
    _upload(client, make_log(2))
    assert client.get("/api/review").json()["checked"]["logs"] == 2
    assert client.post(f"/api/library/{first['id']}/close").status_code == 200
    assert client.get("/api/review").json()["checked"]["logs"] == 1
