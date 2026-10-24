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


def test_preamble_and_placeholder_values():
    raw = (
        b"C:\\logs\\CONCATENATED.LRD\r\n0:00.000 to 0:01.000 at 25Hz\r\n\r\n"
        b"Time, ect1, vehicleSpeed\r\n0.000, ####, ####\r\n"
        b"0.040, 82.6, 0.0\r\n0.080, 82.6, 1.5\r\n0.120, 82.7, 2.0\r\n"
    )
    p = parse_csv(raw)
    assert list(p.df.columns) == ["time_s", "ect1", "vehicleSpeed"]
    assert len(p.df) == 4
    assert np.isnan(p.df["ect1"].iloc[0])
    assert p.df["time_s"].iloc[-1] == pytest.approx(0.12)
    assert any("skipped 3 line" in a for a in p.meta["assumptions"])
    assert "second row treated as units" not in p.meta["assumptions"]


def test_units_guessed_from_names_and_reported():
    raw = b"Time, ect1, vehicleSpeed, mystery\n0.0, 80, 1, 5\n0.1, 81, 2, 6\n0.2, 82, 3, 7\n"
    p = parse_csv(raw)
    units = {c["name"]: c["unit"] for c in p.meta["channels"]}
    assert units == {"ect1": "°C", "vehicleSpeed": "km/h", "mystery": ""}
    assert any("units guessed" in a and "ect1 = °C" in a for a in p.meta["assumptions"])


def test_life_racing_export_start_time_and_states():
    pre = (
        b"C:/Logs/2025-11-19 11-53-32 plus 0h00m30s F88#1 Dyno.LRD\r\n"
        b"0:00.000 to 0:01.000 at 10Hz\r\n\r\n"
    )
    rows = ["Time, rpm, fan1, junk"]
    for i in range(20):
        rows.append(f"{i / 10:.3f}, {1000 + i}, {'ON' if i % 4 < 2 else 'OFF'}, {'x%d' % i}")
    p = parse_csv(pre + "\r\n".join(rows).encode() + b"\r\n")
    assert p.meta["started_at"] == "2025-11-19T11-53-32".replace("11-53-32", "11:54:02")
    fan = next(c for c in p.meta["channels"] if c["name"] == "fan1")
    assert fan["states"] == {"0": "OFF", "1": "ON"}
    assert set(p.df["fan1"].unique()) == {0.0, 1.0}
    assert "junk" not in p.df.columns  # unique text per row is not a state channel
