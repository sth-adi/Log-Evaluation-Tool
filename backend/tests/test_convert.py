import time

import pytest

from backend.app import lifeview


@pytest.fixture()
def fake_lifeview(monkeypatch, synthetic):
    """Pretend LifeView exists and export the synthetic ECU log as the CSV."""
    ecu, _ = synthetic
    calls = []

    def runner(lrd, progress):
        calls.append(lrd.name)
        progress("Exporting")
        out = lrd.with_name(lrd.stem + " ALL.csv")
        out.write_text(f"C:/x/{lrd.name}\r\nrange\r\n\r\n" + ecu.to_csv(index=False))
        return out

    monkeypatch.setattr(lifeview, "RUNNER", runner)
    monkeypatch.setattr(lifeview, "status", lambda: {"available": True, "reason": ""})
    monkeypatch.setattr(lifeview, "lifeview_running", lambda: False)
    monkeypatch.setattr(lifeview, "_current", None)
    return calls


def wait_done(client, job_id, timeout=15):
    t = time.time()
    while time.time() - t < timeout:
        job = client.get(f"/api/convert/{job_id}").json()
        if job["state"] != "running":
            return job
        time.sleep(0.05)
    raise AssertionError("conversion did not finish")


def test_converts_and_imports_in_name_order(client, fake_lifeview):
    files = [
        ("files", ("2025-11-19 11-49-58 plus 0h00m00s b.LRD", b"lrd-bytes")),
        ("files", ("2025-11-19 11-42-03 plus 0h00m00s a.LRD", b"lrd-bytes")),
    ]
    r = client.post("/api/convert", files=files)
    assert r.status_code == 202
    job = wait_done(client, r.json()["id"])
    assert job["state"] == "done" and job["imported"] == 2
    assert fake_lifeview[0].startswith("2025-11-19 11-42-03")  # earliest log first
    sources = client.get("/api/sources").json()
    assert len(sources) == 2 and all(s["started_at"] for s in sources)
    assert all(i["csv"] for i in job["items"])


def test_failure_in_one_log_does_not_stop_the_rest(client, fake_lifeview, monkeypatch):
    good = lifeview.RUNNER

    def flaky(lrd, progress):
        if "bad" in lrd.name:
            raise RuntimeError("LifeView did not open the log")
        return good(lrd, progress)

    monkeypatch.setattr(lifeview, "RUNNER", flaky)
    files = [("files", ("1 bad.LRD", b"x")), ("files", ("2 ok.LRD", b"x"))]
    job = wait_done(client, client.post("/api/convert", files=files).json()["id"])
    states = {i["name"]: i["state"] for i in job["items"]}
    assert states == {"1 bad.LRD": "failed", "2 ok.LRD": "done"}
    assert "did not open" in job["items"][0]["error"]


def test_rejects_other_files_and_reports_missing_lifeview(client, fake_lifeview, monkeypatch):
    assert client.post("/api/convert", files=[("files", ("notes.csv", b"x"))]).status_code == 422
    monkeypatch.setattr(lifeview, "status", lambda: {"available": False, "reason": "LifeView was not found"})
    r = client.post("/api/convert", files=[("files", ("a.LRD", b"x"))])
    assert r.status_code == 422 and "not found" in r.json()["detail"]
    assert client.get("/api/convert/status").json()["available"] is False


def test_refuses_while_lifeview_is_open_or_busy(client, fake_lifeview, monkeypatch):
    monkeypatch.setattr(lifeview, "lifeview_running", lambda: True)
    r = client.post("/api/convert", files=[("files", ("a.LRD", b"x"))])
    assert r.status_code == 409 and "already open" in r.json()["detail"]
    assert client.get("/api/convert/nope").status_code == 404
