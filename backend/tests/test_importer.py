import numpy as np
import pytest

from backend.app.importer import ImportErrorDetail, parse_csv


def _csv_bytes(df):
    return df.to_csv(index=False).encode()


def test_ecu_seconds_detected(synthetic):
    ecu, _ = synthetic
    p = parse_csv(_csv_bytes(ecu))
    assert p.df["time_s"].iloc[0] == 0
    assert p.meta["time_unit"] == "s"
    assert p.meta["sample_rate_hz"] == pytest.approx(100, rel=0.02)
    assert p.meta["gaps"] == 1  # the injected dropout
    assert {c["name"] for c in p.meta["channels"]} >= {"RPM", "TPS", "VehicleSpeed"}


def test_hcu_milliseconds_converted(synthetic):
    _, hcu = synthetic
    p = parse_csv(_csv_bytes(hcu))
    assert p.meta["time_unit"] == "ms"
    assert p.df["time_s"].iloc[-1] == pytest.approx(hcu["Timestamp_ms"].iloc[-1] / 1000)
    units = {c["name"]: c["unit"] for c in p.meta["channels"]}
    assert units["Motor_Torque_Nm"] == "Nm"
    assert units["Pack_Voltage_V"] == "V"
    assert units["Motor_Temp_C"] == "°C"
    assert units["SOC_pct"] == "%"


def test_semicolon_units_row_and_text_column():
    raw = b"Time (s);RPM;Note;Temp\ns;rpm;;degC\n0;1000;a;50\n0.1;1100;b;51\n0.2;1200;c;52\n"
    p = parse_csv(raw)
    assert p.df.columns.tolist() == ["time_s", "RPM", "Temp"]
    units = {c["name"]: c["unit"] for c in p.meta["channels"]}
    assert units == {"RPM": "rpm", "Temp": "degC"}
    assert any("non-numeric" in w for w in p.meta["warnings"])


def test_profile_overrides():
    raw = b"clock,a\n0,1\n500,2\n1000,3\n"
    p = parse_csv(raw, {"time_column": "clock", "time_unit": "ms", "rename": {"a": "Speed"}})
    assert p.df["time_s"].tolist() == [0.0, 0.5, 1.0]
    assert "Speed" in p.df.columns


def test_unsorted_and_duplicate_time_repaired():
    raw = b"Time,x\n0.2,3\n0.0,1\n0.1,2\n0.1,2\n"
    p = parse_csv(raw)
    assert p.df["time_s"].tolist() == pytest.approx([0.0, 0.1, 0.2])
    assert len(p.meta["warnings"]) >= 2


def test_no_time_column_errors():
    with pytest.raises(ImportErrorDetail):
        parse_csv(b"a,b\n3,1\n1,2\n2,3\n")


def test_empty_file_errors():
    with pytest.raises(ImportErrorDetail):
        parse_csv(b"   \n")
