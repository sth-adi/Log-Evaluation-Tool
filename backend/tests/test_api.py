import io

import pytest


def _upload(client, df, **form):
    return client.post(
        "/api/sources",
        files={"file": ("log.csv", io.BytesIO(df.to_csv(index=False).encode()), "text/csv")},
        data=form,
    )


def test_import_list_signals_offset_delete(client, synthetic):
    ecu, hcu = synthetic
    r = _upload(client, ecu, label="ECU run", kind="ecu")
    assert r.status_code == 200, r.text
    ecu_src = r.json()
    r = _upload(client, hcu, label="HCU run", kind="hcu")
    hcu_src = r.json()

    assert [s["label"] for s in client.get("/api/sources").json()] == ["ECU run", "HCU run"]

    r = client.get(
        f"/api/sources/{ecu_src['id']}/signals", params={"channels": "RPM,TPS", "px": 400}
    )
    assert r.status_code == 200
    body = r.json()
    assert set(body["channels"]) == {"RPM", "TPS"}
    assert len(body["channels"]["RPM"]["t"]) <= 2 * 400 + 4
    assert len(body["channels"]["RPM"]["t"]) == len(body["channels"]["RPM"]["v"])

    # zoomed-in window returns finer data than the overview
    r2 = client.get(
        f"/api/sources/{ecu_src['id']}/signals",
        params={"channels": "RPM", "t0": 20, "t1": 22, "px": 400},
    )
    z = r2.json()
    assert z["full_resolution"] is True
    assert min(z["channels"]["RPM"]["t"]) >= 19.9

    # offset shifts the returned time axis (HCU logs 2.35 s after the ECU)
    base = client.get(
        f"/api/sources/{hcu_src['id']}/signals", params={"channels": "SOC_pct", "px": 50}
    ).json()
    p = client.patch(f"/api/sources/{hcu_src['id']}", json={"offset_s": 2.35})
    assert p.json()["offset_s"] == 2.35
    shifted = client.get(
        f"/api/sources/{hcu_src['id']}/signals", params={"channels": "SOC_pct", "px": 50}
    ).json()
    assert abs(shifted["channels"]["SOC_pct"]["t"][0] - base["channels"]["SOC_pct"]["t"][0] - 2.35) < 1e-3

    assert client.delete(f"/api/sources/{hcu_src['id']}").status_code == 204
    assert client.get(f"/api/sources/{hcu_src['id']}").status_code == 404


def test_bad_inputs(client, synthetic):
    ecu, _ = synthetic
    assert _upload(client, ecu, kind="spaceship").status_code == 422
    src = _upload(client, ecu).json()
    r = client.get(f"/api/sources/{src['id']}/signals", params={"channels": "Nope"})
    assert r.status_code == 422
    assert client.get("/api/sources/..%2f..%2fetc%2fpasswd").status_code in (404, 422)
    assert client.get("/api/does-not-exist").status_code == 404
    assert client.get("/api/sources/zzzzzzzzzz/signals", params={"channels": "x"}).status_code == 404
    bad = client.post(
        "/api/sources",
        files={"file": ("x.csv", io.BytesIO(b"a,b\n3,1\n1,2\n"), "text/csv")},
    )
    assert bad.status_code == 422


def test_missing_samples_are_not_zero(client):
    raw = b"hdr\r\nTime, a\r\n0.0, ####\r\n0.1, 5.0\r\n0.2, 6.0\r\n0.3, 7.0\r\n"
    src = client.post("/api/sources", files={"file": ("x.csv", raw)}, data={"kind": "ecu"}).json()
    sig = client.get(f"/api/sources/{src['id']}/signals", params={"channels": "a"}).json()
    assert 0.0 not in sig["channels"]["a"]["v"]


def test_arrange_orders_by_start_time(client):
    def log(stamp):
        head = f"C:/x/{stamp} plus 0h00m00s a.LRD\r\nrange\r\n\r\n".encode()
        body = "\r\n".join(["Time, v"] + [f"{i / 10:.1f}, {i}" for i in range(50)]).encode()
        return head + body

    late = client.post("/api/sources", files={"file": ("late.csv", log("2025-11-19 12-00-00"))}).json()
    early = client.post("/api/sources", files={"file": ("early.csv", log("2025-11-19 11-00-00"))}).json()
    out = {r["id"]: r for r in client.post("/api/arrange", json={"mode": "sequential", "gap_s": 1}).json()}
    assert out[early["id"]]["offset_s"] == 0
    assert out[late["id"]]["offset_s"] == pytest.approx(early["duration_s"] + 1)
    out = {r["id"]: r for r in client.post("/api/arrange", json={"mode": "real"}).json()}
    assert out[late["id"]]["offset_s"] == 3600
    assert client.post("/api/arrange", json={"mode": "x"}).status_code == 422
