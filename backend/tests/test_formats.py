import io

import numpy as np
import pandas as pd
import pytest


def post(client, name, data):
    return client.post("/api/sources", files={"file": (name, io.BytesIO(data), "application/octet-stream")})


def test_parquet_round_trips_our_own_export(client, synthetic):
    ecu, _ = synthetic
    src = client.post("/api/sources", files={"file": ("a.csv", io.BytesIO(ecu.to_csv(index=False).encode()), "text/csv")}).json()
    exported = client.get(f"/api/sources/{src['id']}/export", params={"format": "parquet"}).content
    r = post(client, "2025-11-19 10-00-00 copy.parquet", exported)
    assert r.status_code == 200, r.text
    back = r.json()
    assert back["rows"] == src["rows"] and {c["name"] for c in back["channels"]} == {c["name"] for c in src["channels"]}
    # the same file again is recognised, not stored twice
    again = post(client, "2025-11-19 10-00-00 copy.parquet", exported).json()
    assert again["id"] == back["id"] and again["reused"] is True


def test_excel_with_units_row(client):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Time", "RPM", "Boost"])
    ws.append(["s", "rpm", "kPa"])
    for i in range(200):
        ws.append([i / 10, 3000 + i * 10, 100 + i % 7])
    buf = io.BytesIO()
    wb.save(buf)
    r = post(client, "run.xlsx", buf.getvalue())
    assert r.status_code == 200, r.text
    src = r.json()
    by = {c["name"]: c for c in src["channels"]}
    assert src["rows"] == 200 and by["RPM"]["unit"] == "rpm" and by["Boost"]["unit"] == "kPa"
    assert src["duration_s"] == pytest.approx(19.9)


def test_bad_files_are_explained_not_crashed(client):
    assert post(client, "x.parquet", b"not parquet").status_code == 422
    assert post(client, "x.xlsx", b"not a workbook").status_code == 422
    assert post(client, "x.mf4", b"not a measurement").status_code == 422


def test_mdf_channels_at_different_rates_share_one_time_base(client, tmp_path):
    asammdf = pytest.importorskip("asammdf")
    from asammdf import MDF, Signal

    fast_t = np.arange(0, 10, 0.01)
    slow_t = np.arange(0, 10, 0.1)
    mdf = MDF(version="4.10")
    mdf.append(Signal(samples=3000 + 500 * fast_t, timestamps=fast_t, name="EngineSpeed", unit="rpm"))
    mdf.append(Signal(samples=20 + slow_t, timestamps=slow_t, name="CoolantTemp", unit="degC"))
    path = tmp_path / "log.mf4"
    mdf.save(str(path), overwrite=True)
    mdf.close()
    r = post(client, "2025-11-19 12-00-00 bus log.mf4", path.read_bytes())
    assert r.status_code == 200, r.text
    src = r.json()
    by = {c["name"]: c for c in src["channels"]}
    assert set(by) == {"EngineSpeed", "CoolantTemp"} and by["EngineSpeed"]["unit"] == "rpm" and by["CoolantTemp"]["unit"] == "degC"
    assert src["sample_rate_hz"] == pytest.approx(100, rel=0.05)  # the fastest channel sets the pace
    assert src["started_at"] == "2025-11-19T12:00:00"
    sig = client.get(f"/api/sources/{src['id']}/signals", params={"channels": "CoolantTemp", "px": 50}).json()
    v = sig["channels"]["CoolantTemp"]["v"]
    assert min(v) == pytest.approx(20, abs=0.2) and max(v) == pytest.approx(29.9, abs=0.3)  # the slow channel is interpolated, not blanked
