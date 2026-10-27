"""Phone access: off by default, key-gated when on, and never able to act on the PC."""

import os

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.app import access
from backend.app.main import app

PHONE = ("192.168.1.50", 50123)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("LET_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("LET_LAN", raising=False)
    access._cache.clear()
    return monkeypatch


def pc():
    return TestClient(app, client=("127.0.0.1", 50000))


def phone():
    return TestClient(app, client=PHONE, follow_redirects=False)


def sharing_on(env):
    env.setenv("LET_LAN", "1")


# --- sharing off (the default) ---------------------------------------------------------------


def test_off_by_default_other_devices_are_refused(env):
    c = phone()
    for path in ("/", "/api/health", "/api/sources"):
        r = c.get(path)
        assert r.status_code == 403, path
    assert "Phone access is off" in c.get("/").text
    assert c.get("/api/health").json()["detail"].startswith("This tool is only open")


def test_off_by_default_the_pc_still_works(env):
    r = pc().get("/api/health")
    assert r.status_code == 200
    assert r.json()["local"] is True and r.json()["sharing"] is False
    assert pc().get("/api/share").json() == {"enabled": False}


def test_a_valid_key_does_not_help_when_sharing_is_off(env):
    sharing_on(env)
    k = access.key()
    env.delenv("LET_LAN")
    assert phone().get(f"/?key={k}").status_code == 403


# --- sharing on ------------------------------------------------------------------------------


def test_no_key_or_wrong_key_is_refused(env):
    sharing_on(env)
    c = phone()
    assert c.get("/api/sources").status_code == 401
    assert c.get("/").status_code == 401
    assert "link on the PC" in c.get("/").text
    assert c.get("/?key=nope").status_code == 401
    assert c.get("/api/sources", cookies={"let_key": "nope"}).status_code == 401
    assert c.get("/api/sources", headers={"cookie": "let_key"}).status_code == 401  # malformed


def test_link_sets_cookie_and_removes_key_from_address(env):
    sharing_on(env)
    k = access.key()
    c = phone()
    r = c.get(f"/some/page?x=1&key={k}&y=2")
    assert r.status_code == 303
    assert r.headers["location"] == "/some/page?x=1&y=2"  # key is gone, other parameters stay
    cookie = r.headers["set-cookie"]
    assert cookie.startswith(f"let_key={k};") and "HttpOnly" in cookie and "SameSite=Lax" in cookie
    r2 = c.get("/api/health", cookies={"let_key": k})
    assert r2.status_code == 200
    body = r2.json()
    assert body["local"] is False and body["sharing"] is True


def test_phone_can_use_the_normal_api_once_signed_in(env, synthetic):
    sharing_on(env)
    k = access.key()
    ecu, _ = synthetic
    import io

    c = phone()
    c.cookies.set("let_key", k)
    up = c.post("/api/sources", files={"file": ("ecu.csv", io.BytesIO(ecu.to_csv(index=False).encode()), "text/csv")}, data={"kind": "ecu"})
    assert up.status_code == 200, up.text
    sid = up.json()["id"]
    sig = c.get(f"/api/sources/{sid}/signals", params={"channels": "RPM", "px": 200})
    assert sig.status_code == 200 and len(sig.json()["channels"]["RPM"]["t"]) > 10


def test_pc_needs_no_key_even_with_sharing_on(env):
    sharing_on(env)
    assert pc().get("/api/health").status_code == 200
    assert pc().get("/api/sources").status_code == 200


def test_websockets_from_other_devices_are_refused(env):
    sharing_on(env)
    with pytest.raises(WebSocketDisconnect) as refused:
        with TestClient(app, client=PHONE).websocket_connect("/api/anything"):
            pass
    assert refused.value.code == 1008


# --- things that act on the PC stay on the PC -------------------------------------------------


@pytest.mark.parametrize(
    "method,path",
    [
        ("post", "/api/convert"),
        ("get", "/api/convert/abc"),
        ("post", "/api/convert/abc/cancel"),
        ("post", "/api/library/folder/open"),
        ("get", "/api/live/ports"),
        ("post", "/api/live/start"),
        ("post", "/api/live/stop"),
        ("get", "/api/share"),
        ("post", "/api/share/reset"),
    ],
)
def test_pc_only_endpoints_refuse_a_signed_in_phone(env, method, path):
    sharing_on(env)
    c = phone()
    c.cookies.set("let_key", access.key())
    r = getattr(c, method)(path, **({"json": {"source": "udp"}} if path.endswith("start") else {}))
    assert r.status_code == 403, (path, r.status_code, r.text)
    assert r.json()["detail"] == "This only works on the PC that runs the tool."


def test_phone_sees_lrd_conversion_as_unavailable(env):
    sharing_on(env)
    c = phone()
    c.cookies.set("let_key", access.key())
    st = c.get("/api/convert/status").json()
    assert st["available"] is False and "PC that runs the tool" in st["reason"]


def test_live_data_can_still_be_watched_from_the_phone(env):
    sharing_on(env)
    c = phone()
    c.cookies.set("let_key", access.key())
    assert c.get("/api/live/status").status_code == 200


# --- the key and the links ---------------------------------------------------------------------


def test_key_is_long_random_and_kept(env):
    k1 = access.key()
    assert len(k1) >= 20
    access._cache.clear()
    assert access.key() == k1  # read back from disk
    if os.name == "posix":  # owner-only file; Windows has no such mode bits
        assert access._key_file().stat().st_mode & 0o077 == 0


def test_reset_signs_old_links_out(env):
    sharing_on(env)
    old = access.key()
    c = phone()
    c.cookies.set("let_key", old)
    assert c.get("/api/sources").status_code == 200
    r = pc().post("/api/share/reset")
    assert r.status_code == 200
    assert access.key() != old
    assert c.get("/api/sources").status_code == 401


def test_reset_refused_when_sharing_is_off(env):
    assert pc().post("/api/share/reset").status_code == 409


def test_share_links_contain_port_and_key(env, monkeypatch):
    sharing_on(env)
    monkeypatch.setattr(access, "lan_addresses", lambda: ["192.168.1.20", "10.0.0.5"])
    c = TestClient(app, base_url="http://127.0.0.1:8123", client=("127.0.0.1", 50000))
    info = c.get("/api/share").json()
    k = access.key()
    assert info == {"enabled": True, "port": 8123, "urls": [f"http://192.168.1.20:8123/?key={k}", f"http://10.0.0.5:8123/?key={k}"]}


def test_sharing_text_for_the_launcher(env):
    assert pc().get("/api/sharing").text == "sharing-off"
    sharing_on(env)
    assert pc().get("/api/sharing").text == "sharing-on"


def test_only_private_addresses_are_offered():
    got = access.usable_addresses(
        ["127.0.0.1", "169.254.10.2", "8.8.8.8", "192.168.1.20", "192.168.1.20", "10.1.2.3", "172.20.0.1", "fe80::1", "garbage"]
    )
    assert got == ["192.168.1.20", "10.1.2.3", "172.20.0.1"]


@pytest.mark.parametrize("host,expected", [("127.0.0.1", True), ("::1", True), ("::ffff:127.0.0.1", True), ("192.168.1.5", False), ("", False), (None, False), ("testclient", False)])
def test_loopback_detection(host, expected):
    assert access.is_loopback(host) is expected
