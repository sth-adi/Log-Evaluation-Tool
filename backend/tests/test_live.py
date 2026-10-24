import io
import socket
import time

import numpy as np
import pandas as pd
import pytest

from backend.app import live


@pytest.fixture(autouse=True)
def fresh_hub():
    live.HUB.stop()
    live.HUB.clear()
    live.HUB.source = None
    live.HUB.error = None
    yield
    live.HUB.stop()
    live.HUB.clear()
    live.HUB.source = None


def wait_for(cond, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_parse_line_json_csv_and_header():
    st: dict = {}
    assert live.parse_line('{"t": 1.5, "rpm": 8000, "name": "x", "ok": true}', st) == {"t": 1.5, "values": {"rpm": 8000.0}}
    assert live.parse_line('{"rpm": 1}', st) == {"t": None, "values": {"rpm": 1.0}}
    assert live.parse_line("not json {", st) is None
    assert live.parse_line("", st) is None
    assert live.parse_line("1,2", st) is None  # numbers before any header are not usable
    assert live.parse_line("time,rpm,tps", st) is None  # the header line
    assert live.parse_line("0.5, 8000, 40", st) == {"t": 0.5, "values": {"rpm": 8000.0, "tps": 40.0}}
    assert live.parse_line("1,2", st) is None  # wrong column count


def test_ring_buffer_wraps_and_new_channels_start_blank():
    hub = live.Hub(capacity=8)
    hub.push_block(np.arange(5.0), {"a": np.arange(5, dtype=np.float32)})
    hub.push_block(np.arange(5.0, 10.0), {"a": np.arange(5, 10, dtype=np.float32), "b": np.ones(5, dtype=np.float32)})
    assert hub.n == 10 and hub.status()["kept"] == 8
    seq, dropped, t, cols = hub.rows_since(0, ["a", "b"])
    assert dropped == 2 and list(t) == [2, 3, 4, 5, 6, 7, 8, 9]  # the two oldest were overwritten
    assert list(cols["a"]) == [2, 3, 4, 5, 6, 7, 8, 9]
    assert np.isnan(cols["b"][:3]).all() and (cols["b"][3:] == 1).all()  # b only existed from row 5
    seq2, dropped2, t2, _ = hub.rows_since(seq, ["a"])
    assert dropped2 == 0 and len(t2) == 0


def test_slow_reader_skips_ahead_instead_of_lagging():
    hub = live.Hub(capacity=100)
    hub.push_block(np.arange(100.0), {"a": np.arange(100, dtype=np.float32)})
    _, dropped, t, _ = hub.rows_since(0, ["a"], limit=10)
    assert len(t) == 10 and t[-1] == 99 and dropped == 90


def test_ingest_status_window_and_clear(client):
    rows = [{"t": i / 10, "values": {"rpm": 1000 + i, "tps1": i}} for i in range(50)]
    r = client.post("/api/live/ingest", json={"rows": rows, "units": {"rpm": "rpm"}})
    assert r.json() == {"accepted": 50}
    st = client.get("/api/live/status").json()
    assert st["rows"] == 50 and st["source"]["kind"] == "push"
    by = {c["name"]: c for c in st["channels"]}
    assert by["rpm"]["last"] == 1049 and by["rpm"]["unit"] == "rpm"
    w = client.get("/api/live/window", params={"channels": "rpm", "seconds": 1}).json()
    assert len(w["t"]) in (10, 11) and w["v"]["rpm"][-1] == 1049  # one second of 10 Hz data
    # flat rows without a "values" wrapper are accepted too
    assert client.post("/api/live/ingest", json={"rows": [{"t": 9.0, "rpm": 5}]}).json() == {"accepted": 1}
    assert client.post("/api/live/clear").json()["rows"] == 0


def test_save_needs_data_then_becomes_an_ordinary_log(client):
    assert client.post("/api/live/save", json={}).status_code == 422
    rows = [{"t": i / 100, "values": {"vehicleSpeed": 50 + i % 7, "rpm": 3000 + i}} for i in range(500)]
    client.post("/api/live/ingest", json={"rows": rows})
    saved = client.post("/api/live/save", json={"label": "Pit lane test"}).json()
    assert saved["label"] == "Pit lane test" and saved["rows"] == 500
    assert {c["name"] for c in saved["channels"]} == {"vehicleSpeed", "rpm"}
    got = client.get(f"/api/sources/{saved['id']}/signals", params={"channels": "rpm", "px": 100}).json()
    assert got["channels"]["rpm"]["v"][-1] == 3499
    assert any(s["id"] == saved["id"] for s in client.get("/api/sources").json())


def test_simulated_session_is_saved_and_lap_analysis_finds_its_laps(client):
    st = client.post("/api/live/start", json={"source": "simulator", "options": {"speed": 80, "seed": 4}}).json()
    assert st["source"]["kind"] == "simulator"
    assert wait_for(lambda: live.HUB.n >= 100 * 130)  # about 130 simulated seconds
    client.post("/api/live/stop")
    assert client.get("/api/live/status").json()["state"] == "stopped"
    saved = client.post("/api/live/save", json={"label": "Sim"}).json()
    laps = client.get(f"/api/sources/{saved['id']}/laps").json()
    assert "lapTime" in laps["found_by"] and len(laps["laps"]) >= 2
    assert laps["laps"][0]["distance_m"] == pytest.approx(602.7, rel=0.03)  # the simulator's circuit
    assert 20 < laps["laps"][0]["duration_s"] < 40


def test_replay_a_library_log_in_real_time(client, synthetic):
    ecu, _ = synthetic
    src = client.post("/api/sources", files={"file": ("a.csv", io.BytesIO(ecu.to_csv(index=False).encode()), "text/csv")}).json()
    st = client.post("/api/live/start", json={"source": "replay", "options": {"source_id": src["id"], "speed": 500}}).json()
    assert st["source"]["kind"] == "replay"
    assert wait_for(lambda: live.HUB.n >= len(ecu))
    assert wait_for(lambda: client.get("/api/live/status").json()["state"] == "stopped")
    assert live.HUB.n == len(ecu)
    seq, _, t, cols = live.HUB.rows_since(0, ["RPM"], limit=len(ecu))
    assert cols["RPM"][100] == pytest.approx(ecu["RPM"].iloc[100], rel=1e-5)


def test_replay_and_serial_errors_are_explained(client):
    r = client.post("/api/live/start", json={"source": "replay", "options": {}})
    assert r.status_code == 422 and "log" in r.json()["detail"].lower()
    r = client.post("/api/live/start", json={"source": "replay", "options": {"source_id": "nope"}})
    assert r.status_code == 422
    r = client.post("/api/live/start", json={"source": "serial", "options": {}})
    assert r.status_code == 422
    assert client.post("/api/live/start", json={"source": "radio"}).status_code == 422


def test_udp_listener_receives_json_and_csv(client):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    client.post("/api/live/start", json={"source": "udp", "options": {"port": port, "host": "127.0.0.1"}})
    tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    for _ in range(50):  # the listener may need a moment to bind
        tx.sendto(b'{"t": 1.0, "rpm": 9000}\n{"t": 1.1, "rpm": 9100}\n', ("127.0.0.1", port))
        if live.HUB.n:
            break
        time.sleep(0.05)
    tx.sendto(b"time,boost\n2.0,1.5\n2.1,1.6\n", ("127.0.0.1", port))
    assert wait_for(lambda: {"rpm", "boost"} <= set(live.HUB.cols))
    assert live.HUB.status()["source"]["kind"] == "udp"
    tx.close()


def test_a_port_in_use_is_reported_on_the_status(client):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    try:
        client.post("/api/live/start", json={"source": "udp", "options": {"port": port, "host": "127.0.0.1"}})
        assert wait_for(lambda: client.get("/api/live/status").json()["error"])
        assert "UDP port" in client.get("/api/live/status").json()["error"]
    finally:
        s.close()


def test_a_bridge_replaces_a_stopped_sources_label(client):
    client.post("/api/live/start", json={"source": "simulator", "options": {"speed": 50}})
    client.post("/api/live/stop")
    client.post("/api/live/ingest", json={"rows": [{"t": 1.0, "values": {"rpm": 1}}]})
    assert client.get("/api/live/status").json()["source"]["kind"] == "push"
