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


def test_math_channels(client, synthetic):
    ecu, _ = synthetic
    src = client.post("/api/sources", files={"file": ("ecu.csv", ecu.to_csv(index=False).encode())}).json()
    sid = src["id"]
    r = client.post(f"/api/sources/{sid}/derived", json={"name": "rps", "expr": "RPM / 60", "unit": "Hz"})
    assert r.status_code == 200
    chan = next(c for c in r.json()["channels"] if c["name"] == "rps")
    assert chan["derived"] and chan["unit"] == "Hz"
    r2 = client.post(f"/api/sources/{sid}/derived", json={"name": "rps2", "expr": "rps * 2"})
    assert r2.status_code == 200  # a formula can use another math channel
    g = client.get(f"/api/sources/{sid}/signals", params={"channels": "RPM,rps,rps2", "px": 500}).json()
    rpm, rps, rps2 = (g["channels"][k]["v"] for k in ("RPM", "rps", "rps2"))
    assert rps[10] == pytest.approx(rpm[10] / 60) and rps2[10] == pytest.approx(rps[10] * 2)
    # errors are reported, not raised
    assert client.post(f"/api/sources/{sid}/derived", json={"name": "bad", "expr": "nope + 1"}).status_code == 422
    assert client.post(f"/api/sources/{sid}/derived", json={"name": "RPM", "expr": "1"}).status_code == 422
    assert client.delete(f"/api/sources/{sid}/derived/rps").status_code == 422  # rps2 uses it
    assert client.delete(f"/api/sources/{sid}/derived/rps2").status_code == 200
    assert client.delete(f"/api/sources/{sid}/derived/rps").status_code == 200


def test_analysis_endpoints(client, synthetic):
    ecu, _ = synthetic
    sid = client.post("/api/sources", files={"file": ("ecu.csv", ecu.to_csv(index=False).encode())}).json()["id"]
    s = client.get(f"/api/sources/{sid}/stats", params={"channels": "RPM,TPS"}).json()
    assert s["channels"]["RPM"]["max"] >= s["channels"]["RPM"]["mean"] >= s["channels"]["RPM"]["min"]
    h = client.get(f"/api/sources/{sid}/histogram", params={"channel": "RPM", "bins": 20}).json()
    assert sum(h["counts"]) == h["total"] > 0
    sp = client.get(f"/api/sources/{sid}/spectrum", params={"channel": "RPM", "t0": 1, "t1": 8}).json()
    assert len(sp["freq_hz"]) == len(sp["amplitude"]) > 10
    sc = client.get(f"/api/sources/{sid}/scatter", params={"x": "TPS", "y": "RPM"}).json()
    assert sc["points"] > 100 and len(sc["x"]) == len(sc["t"])
    assert client.get(f"/api/sources/{sid}/stats", params={"channels": "nope"}).status_code == 422
    assert client.get(f"/api/sources/{sid}/stats", params={"channels": "RPM", "t0": 1e6}).status_code == 422
    client.post(f"/api/sources/{sid}/derived", json={"name": "r2", "expr": "RPM * 2"})
    d = client.get(f"/api/sources/{sid}/stats", params={"channels": "RPM,r2"}).json()["channels"]
    assert d["r2"]["max"] == pytest.approx(2 * d["RPM"]["max"])


def test_event_rules(client, synthetic):
    ecu, _ = synthetic
    sid = client.post("/api/sources", files={"file": ("ecu.csv", ecu.to_csv(index=False).encode())}).json()["id"]
    top = float(ecu["RPM"].max())
    body = {"name": "High rpm", "expr": f"RPM > {top * 0.9}", "min_duration_s": 0.05}
    r = client.post(f"/api/sources/{sid}/rules", json=body)
    assert r.status_code == 200 and r.json()["rules"][0]["name"] == "High rpm"
    ev = client.get(f"/api/sources/{sid}/events").json()
    assert ev and all(e["rule"] == "High rpm" and e["t_end"] >= e["t_start"] for e in ev)
    assert [e["t_start"] for e in ev] == sorted(e["t_start"] for e in ev)
    # offsets move the events
    client.patch(f"/api/sources/{sid}", json={"offset_s": 100})
    assert client.get(f"/api/sources/{sid}/events").json()[0]["t_start"] > 100
    assert client.post(f"/api/sources/{sid}/rules", json=body).status_code == 422  # duplicate name
    assert client.post(f"/api/sources/{sid}/rules", json={"name": "x", "expr": "nope > 1"}).status_code == 422
    assert client.delete(f"/api/sources/{sid}/rules/High rpm").status_code == 200
    assert client.get(f"/api/sources/{sid}/events").json() == []


def test_report_is_self_contained_html(client, synthetic):
    ecu, _ = synthetic
    sid = client.post("/api/sources", files={"file": ("ecu.csv", ecu.to_csv(index=False).encode())}).json()["id"]
    client.post(f"/api/sources/{sid}/rules", json={"name": "Wide open", "expr": "TPS > 50"})
    r = client.get(f"/api/sources/{sid}/report", params={"channels": "RPM,TPS"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    html = r.text
    assert html.count("<svg") == 2 and "Wide open" in html and "RPM" in html
    assert "<script" not in html and "http://" not in html.replace("http://www.w3.org/2000/svg", "")
    assert client.get(f"/api/sources/{sid}/report", params={"channels": ""}).status_code == 422
    assert client.get(f"/api/sources/{sid}/report", params={"channels": "nope"}).status_code == 422
