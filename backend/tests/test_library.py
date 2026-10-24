import io

from backend.app import lifeview


def csv_bytes(synthetic, head="C:/a/log.LRD"):
    ecu, _ = synthetic
    return (f"{head}\r\nrange\r\n\r\n" + ecu.to_csv(index=False)).encode()


def post(client, name, data):
    return client.post("/api/sources", files={"file": (name, io.BytesIO(data))})


def test_same_data_is_not_stored_twice_even_from_another_path(client, synthetic):
    a = post(client, "one ALL.csv", csv_bytes(synthetic, "C:/a/log.LRD")).json()
    b = post(client, "copy.csv", csv_bytes(synthetic, "D:/elsewhere/log.LRD")).json()
    assert b["id"] == a["id"] and b["reused"] is True and "reused" not in a
    assert len(client.get("/api/sources").json()) == 1
    assert len(client.get("/api/library").json()) == 1


def test_closed_logs_stay_in_the_library_and_reopen(client, synthetic):
    a = post(client, "one.csv", csv_bytes(synthetic)).json()
    assert client.post(f"/api/library/{a['id']}/close").json()["open"] is False
    assert client.get("/api/sources").json() == []           # gone from the view
    lib = client.get("/api/library").json()
    assert len(lib) == 1 and lib[0]["open"] is False and lib[0]["channels"] > 3
    again = post(client, "one.csv", csv_bytes(synthetic)).json()   # importing it again reopens it
    assert again["id"] == a["id"] and again["reused"] and again["open"] is True
    assert len(client.get("/api/sources").json()) == 1
    client.post(f"/api/library/{a['id']}/close")
    assert client.post(f"/api/library/{a['id']}/open").json()["open"] is True
    assert client.post("/api/library/nope/open").status_code == 404


def test_arrange_and_views_only_use_open_logs(client, synthetic):
    a = post(client, "2025-11-19 11-00-00 a.csv", csv_bytes(synthetic, "C:/x/2025-11-19 11-00-00 plus 0h00m00s a.LRD")).json()
    client.post(f"/api/library/{a['id']}/close")
    assert client.post("/api/arrange", json={"mode": "sequential"}).json() == []


def test_lrd_already_converted_is_not_converted_again(client, monkeypatch, synthetic):
    import time

    calls = []

    def runner(lrd, progress):
        calls.append(lrd.name)
        out = lrd.with_name(lrd.stem + " ALL.csv")
        out.write_bytes(csv_bytes(synthetic, f"C:/tmp/{lrd.name}"))
        return out

    monkeypatch.setattr(lifeview, "RUNNER", runner)
    monkeypatch.setattr(lifeview, "status", lambda: {"available": True, "reason": ""})
    monkeypatch.setattr(lifeview, "lifeview_running", lambda: False)
    monkeypatch.setattr(lifeview, "_current", None)

    def convert(data):
        job = client.post("/api/convert", files=[("files", ("2025-11-19 11-00-00 plus 0h00m00s a.LRD", data))]).json()
        for _ in range(300):
            j = client.get(f"/api/convert/{job['id']}").json()
            if j["state"] != "running":
                return j
            time.sleep(0.05)
        raise AssertionError("conversion did not finish")

    first = convert(b"lrd-bytes")
    assert first["items"][0]["stage"] == "" and len(calls) == 1
    client.post(f"/api/library/{first['items'][0]['source_id']}/close")
    second = convert(b"lrd-bytes")                                # same LRD again: LifeView is not used
    assert len(calls) == 1 and second["items"][0]["stage"] == "Already in your library"
    assert len(client.get("/api/sources").json()) == 1            # and it is back in view, once
    other = convert(b"different-lrd-bytes")                       # new LRD, but its CSV data is the same
    assert len(calls) == 2 and other["items"][0]["stage"] == "Already in your library"
    assert len(client.get("/api/library").json()) == 1
    assert len(convert(b"different-lrd-bytes")["items"]) == 1 and len(calls) == 2   # now remembered too
