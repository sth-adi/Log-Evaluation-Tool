import io

import numpy as np
import pytest

can = pytest.importorskip("can")
cantools = pytest.importorskip("cantools")
from cantools.database.can import Message, Signal  # noqa: E402
from cantools.database.conversion import BaseConversion  # noqa: E402


def make_dbc() -> bytes:
    engine = Message(
        0x100, "Engine", 8,
        [
            Signal("EngineSpeed", 0, 16, conversion=BaseConversion.factory(scale=0.25), unit="rpm"),
            Signal("Gear", 16, 4, conversion=BaseConversion.factory(choices={0: "N", 1: "First", 2: "Second"})),
        ],
    )
    temps = Message(0x200, "Temps", 8, [Signal("CoolantTemp", 0, 8, conversion=BaseConversion.factory(offset=-40), unit="degC")])
    return cantools.database.Database(messages=[engine, temps]).as_dbc_string().encode()


def write_log(path, frames, writer=None):
    """frames: (timestamp, arbitration_id, data bytes)."""
    with (writer or can.ASCWriter)(str(path)) as w:
        for ts, aid, data in frames:
            w(can.Message(timestamp=ts, arbitration_id=aid, data=data, is_extended_id=False, channel=0))


def engine(rpm, gear):
    raw = int(rpm / 0.25)
    return bytes([raw & 0xFF, (raw >> 8) & 0xFF, gear, 0, 0, 0, 0, 0])


def frames(seconds=10.0):
    out = []
    for i in range(int(seconds * 100)):  # Engine at 100 Hz
        t = i / 100
        out.append((1000.0 + t, 0x100, engine(2000 + 100 * t, 1 if t < 5 else 2)))
    for i in range(int(seconds * 10)):  # Temps at 10 Hz
        t = i / 10
        out.append((1000.0 + t + 0.0005, 0x200, bytes([int(80 + t) + 40, 0, 0, 0, 0, 0, 0, 0])))
    return sorted(out)


def add_dbc(client, name="Car"):
    r = client.post("/api/can/dbc", files={"file": ("car.dbc", io.BytesIO(make_dbc()), "text/plain")}, data={"name": name})
    assert r.status_code == 200, r.text
    return r.json()


def upload(client, path, dbc_ids, name=None):
    return client.post(
        "/api/sources",
        files={"file": (name or path.name, io.BytesIO(path.read_bytes()), "application/octet-stream")},
        data={"dbc": ",".join(dbc_ids)},
    )


def test_dbc_library_validates_dedupes_and_deletes(client):
    a = add_dbc(client)
    assert a["messages"] == 2 and a["signals"] == 3
    assert add_dbc(client, "Same file again")["id"] == a["id"]  # one copy
    assert [d["id"] for d in client.get("/api/can/dbc").json()] == [a["id"]]
    bad = client.post("/api/can/dbc", files={"file": ("x.dbc", io.BytesIO(b"this is not a dbc"), "text/plain")})
    assert bad.status_code == 422
    assert client.delete(f"/api/can/dbc/{a['id']}").status_code == 204
    assert client.delete(f"/api/can/dbc/{a['id']}").status_code == 404
    assert client.get("/api/can/dbc").json() == []


@pytest.mark.parametrize("writer_name, ext", [("ASCWriter", "asc"), ("BLFWriter", "blf")])
def test_decodes_scaled_values_units_and_states(client, tmp_path, writer_name, ext):
    dbc = add_dbc(client)["id"]
    path = tmp_path / f"2025-11-19 12-00-00 car.{ext}"
    write_log(path, frames(), getattr(can, writer_name))
    r = upload(client, path, [dbc])
    assert r.status_code == 200, r.text
    src = r.json()
    by = {c["name"]: c for c in src["channels"]}
    assert set(by) == {"EngineSpeed", "Gear", "CoolantTemp"}
    assert by["EngineSpeed"]["unit"] == "rpm" and by["CoolantTemp"]["unit"] == "degC"
    assert by["Gear"]["states"] == {"0": "N", "1": "First", "2": "Second"}
    assert by["EngineSpeed"]["min"] == pytest.approx(2000, abs=1) and by["EngineSpeed"]["max"] == pytest.approx(2999, abs=2)
    assert by["CoolantTemp"]["min"] == pytest.approx(80, abs=0.5) and by["CoolantTemp"]["max"] == pytest.approx(89, abs=0.5)
    assert src["duration_s"] == pytest.approx(9.99, abs=0.05)
    assert src["started_at"] == "2025-11-19T12:00:00"
    # the slow 10 Hz temperature is held between frames, so it has a value at every sample
    sig = client.get(f"/api/sources/{src['id']}/signals", params={"channels": "CoolantTemp", "px": 400}).json()
    assert None not in sig["channels"]["CoolantTemp"]["v"]


def test_unknown_ids_are_reported_not_dropped_quietly(client, tmp_path):
    dbc = add_dbc(client)["id"]
    extra = [(1000.0 + i / 50, 0x7FF, bytes(8)) for i in range(100)]
    path = tmp_path / "log.asc"
    write_log(path, sorted(frames(5.0) + extra))
    src = upload(client, path, [dbc]).json()
    note = next(w for w in src["warnings"] if "0x7FF" in w)
    assert "100" in note and "does not describe" in note


def test_a_signal_that_goes_silent_becomes_a_gap(client, tmp_path):
    dbc = add_dbc(client)["id"]
    fr = [f for f in frames(10.0) if not (f[1] == 0x200 and f[0] > 1003.0)]  # temperature stops after 3 s
    path = tmp_path / "log.asc"
    write_log(path, fr)
    src = upload(client, path, [dbc]).json()
    v = client.get(f"/api/sources/{src['id']}/signals", params={"channels": "CoolantTemp", "px": 2000}).json()["channels"]["CoolantTemp"]
    vals = np.array([np.nan if x is None else x for x in v["v"]])
    t = np.array(v["t"])
    assert np.isfinite(vals[t < 3]).all() and np.isnan(vals[t > 5]).all()  # held briefly, then honestly blank


def test_errors_are_explained(client, tmp_path):
    dbc = add_dbc(client)["id"]
    path = tmp_path / "log.asc"
    write_log(path, frames(2.0))
    assert upload(client, path, []).status_code == 422  # a DBC is required
    assert "DBC" in upload(client, path, []).json()["detail"]
    assert upload(client, path, ["nope"]).status_code == 422
    other = tmp_path / "other.asc"
    write_log(other, [(1000.0 + i / 10, 0x555, bytes(8)) for i in range(50)])
    r = upload(client, other, [dbc])
    assert r.status_code == 422 and "0x555" in r.json()["detail"]  # says what the log does contain
    junk = tmp_path / "junk.blf"
    junk.write_bytes(b"not a can log")
    assert upload(client, junk, [dbc]).status_code == 422
