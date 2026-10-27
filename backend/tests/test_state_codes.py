import io
import json

import numpy as np
import pandas as pd


def _log(gears):
    n = 400
    gear = [gears[(i // 50) % len(gears)] for i in range(n)]
    return pd.DataFrame({"time_s": np.arange(n) / 100, "rpm": np.linspace(1000, 9000, n), "gear": gear})


def _upload(client, df):
    r = client.post(
        "/api/sources", files={"file": ("log.csv", io.BytesIO(df.to_csv(index=False).encode()), "text/csv")}
    )
    assert r.status_code == 200, r.text
    return r.json()


def _codes(src):
    gear = next(c for c in src["channels"] if c["name"] == "gear")
    return {label: int(code) for code, label in gear["states"].items()}


def test_a_label_gets_the_same_number_in_every_log(client):
    a = _upload(client, _log(["FIRST", "NEUTRAL", "SECOND", "THIRD"]))
    b = _upload(client, _log(["NEUTRAL", "SECOND"]))  # sorted alone, NEUTRAL would be 0 here
    assert _codes(a)["NEUTRAL"] == _codes(b)["NEUTRAL"]
    assert _codes(b)["SECOND"] == _codes(a)["SECOND"]


def test_the_stored_values_follow_the_shared_numbers(client, tmp_path):
    _upload(client, _log(["FIRST", "NEUTRAL", "SECOND"]))
    b = _upload(client, _log(["NEUTRAL", "SECOND"]))
    df = pd.read_parquet(tmp_path / "sources" / b["id"] / "data.parquet")
    by_code = {v: k for k, v in _codes(b).items()}
    assert set(by_code[int(v)] for v in df["gear"].unique()) == {"NEUTRAL", "SECOND"}


def test_a_later_log_adds_its_new_label_without_moving_the_old_ones(client):
    a = _upload(client, _log(["FIRST", "NEUTRAL"]))
    b = _upload(client, _log(["FIRST", "NEUTRAL", "FOURTH"]))
    assert _codes(b)["FIRST"] == _codes(a)["FIRST"] and _codes(b)["NEUTRAL"] == _codes(a)["NEUTRAL"]
    assert "FOURTH" in _codes(b)


def test_logs_imported_before_the_shared_numbering_are_renumbered(client, tmp_path):
    a = _upload(client, _log(["FIRST", "NEUTRAL", "SECOND", "THIRD"]))
    b = _upload(client, _log(["NEUTRAL", "SECOND"]))
    # put log b back the way an older version stored it: numbered alone, no marker
    folder = tmp_path / "sources" / b["id"]
    meta = json.loads((folder / "meta.json").read_text())
    df = pd.read_parquet(folder / "data.parquet")
    alone = {"NEUTRAL": 0.0, "SECOND": 1.0}
    inv = {float(k): v for k, v in {str(v): k for k, v in _codes(b).items()}.items()}
    df["gear"] = df["gear"].map(lambda v: alone[inv[v]])
    for c in meta["channels"]:
        if c["name"] == "gear":
            c["states"] = {"0": "NEUTRAL", "1": "SECOND"}
    meta.pop("states_stable")
    (folder / "meta.json").write_text(json.dumps(meta))
    df.to_parquet(folder / "data.parquet", index=False)

    import backend.app.store as store

    store._codes_done.clear()
    again = next(s for s in client.get("/api/sources").json() if s["id"] == b["id"])
    assert _codes(again)["NEUTRAL"] == _codes(a)["NEUTRAL"]
    fixed = pd.read_parquet(folder / "data.parquet")
    by_code = {v: k for k, v in _codes(again).items()}
    assert set(by_code[int(v)] for v in fixed["gear"].unique()) == {"NEUTRAL", "SECOND"}
