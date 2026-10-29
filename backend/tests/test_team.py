"""Team accounts: the PC makes them, everyone else signs in, nothing leaks without one."""

import pytest
from fastapi.testclient import TestClient

from backend.app import access, team
from backend.app.main import app

PHONE = ("192.168.1.50", 50123)
PW = "correct horse battery"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("LET_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("LET_LAN", raising=False)
    monkeypatch.setenv("LET_TEAM", "1")
    access._cache.clear()
    team._tries.clear()
    return monkeypatch


def pc():
    return TestClient(app, client=("127.0.0.1", 50000))


def remote():
    return TestClient(app, client=PHONE, follow_redirects=False)


def make(name="sam", role="member", password=PW):
    r = pc().put(f"/api/team/users/{name}", json={"password": password, "role": role})
    assert r.status_code == 200, r.text
    return r.json()


def sign_in(name="sam", password=PW):
    c = remote()
    r = c.post("/api/team/login", json={"name": name, "password": password})
    return c, r


# --- the gate ----------------------------------------------------------------------------------


def test_without_an_account_other_devices_get_a_sign_in_page_and_nothing_else(env):
    c = remote()
    page = c.get("/")
    assert page.status_code == 401 and "Sign in" in page.text
    for path in ("/api/sources", "/api/review", "/api/health", "/api/team/users"):
        assert c.get(path).status_code == 401, path


def test_the_sharing_key_does_not_open_team_mode(env):
    k = access.key()
    assert remote().get(f"/?key={k}").status_code == 401
    assert remote().get("/api/sources", cookies={"let_key": k}).status_code == 401


def test_the_pc_itself_needs_no_sign_in_and_is_an_administrator(env):
    me = pc().get("/api/team/me").json()
    assert me == {"team": True, "user": "this PC", "role": "admin", "local": True}
    assert pc().get("/api/sources").status_code == 200


def test_a_request_through_a_proxy_on_the_pc_is_not_the_pc(env):
    # a tunnel running on the PC connects from 127.0.0.1 and names the real caller in a header
    c = pc()
    assert c.get("/api/sources", headers={"X-Forwarded-For": "203.0.113.9"}).status_code == 401
    assert c.get("/api/sources", headers={"CF-Connecting-IP": "203.0.113.9"}).status_code == 401
    assert c.get("/api/sources", headers={"Forwarded": "for=203.0.113.9"}).status_code == 401


def test_a_proxy_header_also_stops_the_pc_only_actions(env, monkeypatch):
    monkeypatch.delenv("LET_TEAM")
    monkeypatch.delenv("LET_LAN", raising=False)
    r = pc().get("/api/sources", headers={"X-Forwarded-For": "203.0.113.9"})
    assert r.status_code == 403  # sharing is off, so a proxied request is refused outright


# --- signing in --------------------------------------------------------------------------------


def test_sign_in_opens_the_tool_and_sign_out_closes_it(env):
    make()
    c, r = sign_in()
    assert r.status_code == 200 and r.json() == {"user": "sam", "role": "member"}
    assert "HttpOnly" in r.headers["set-cookie"] and "SameSite=strict" in r.headers["set-cookie"]
    assert c.get("/api/sources").status_code == 200
    assert c.get("/api/team/me").json()["user"] == "sam"
    assert c.post("/api/team/logout").status_code == 204
    assert c.get("/api/sources").status_code == 401


def test_wrong_password_and_unknown_name_look_the_same(env):
    make()
    a = sign_in(password="wrong password here")[1]
    b = sign_in(name="nobody")[1]
    assert a.status_code == b.status_code == 401 and a.json() == b.json()


def test_the_name_is_not_case_sensitive(env):
    make("Sam")
    assert sign_in("sam")[1].status_code == 200


def test_too_many_wrong_passwords_lock_the_name_out_even_for_the_right_one(env):
    make()
    for _ in range(team.MAX_TRIES):
        assert sign_in(password="wrong password here")[1].status_code == 401
    locked = sign_in()[1]
    assert locked.status_code == 429 and "minutes" in locked.json()["detail"]
    # another name from the same address is not locked, and neither is the same name from another address
    make("alex")
    assert sign_in("alex")[1].status_code == 200


def test_passwords_are_kept_hashed(env, tmp_path):
    make()
    text = (tmp_path / "team_users.json").read_text()
    assert PW not in text and "scrypt$" in text
    assert team.check_password(PW, team.users()["sam"]["hash"])
    assert not team.check_password("something else entirely", team.users()["sam"]["hash"])


def test_a_session_token_is_not_stored_as_given(env, tmp_path):
    make()
    c, _ = sign_in()
    token = c.cookies.get("let_session")
    assert token and token not in (tmp_path / "team_sessions.json").read_text()


# --- accounts ----------------------------------------------------------------------------------


def test_bad_names_and_short_passwords_are_refused(env):
    for name, pw in (("a", PW), ("has space", PW), ("../x", PW), ("sam", "short")):
        r = pc().put(f"/api/team/users/{name}", json={"password": pw})
        assert r.status_code in (404, 405, 422), (name, r.status_code)
    assert pc().put("/api/team/users/sam", json={}).status_code == 422  # a new account needs a password
    assert pc().put("/api/team/users/sam", json={"password": PW, "role": "boss"}).status_code == 422


def test_deleting_an_account_ends_its_sign_in(env):
    make()
    c, _ = sign_in()
    assert c.get("/api/sources").status_code == 200
    assert pc().delete("/api/team/users/sam").status_code == 204
    assert c.get("/api/sources").status_code == 401
    assert pc().delete("/api/team/users/sam").status_code == 404


def test_a_new_password_signs_the_old_sign_ins_out(env):
    make()
    c, _ = sign_in()
    assert pc().put("/api/team/users/sam", json={"password": "a different long password"}).status_code == 200
    assert c.get("/api/sources").status_code == 401
    assert sign_in(password="a different long password")[1].status_code == 200


def test_only_administrators_manage_accounts(env):
    make("sam", "member")
    make("root", "admin")
    member, _ = sign_in("sam")
    assert member.get("/api/team/users").status_code == 403
    assert member.put("/api/team/users/eve", json={"password": PW}).status_code == 403
    admin, _ = sign_in("root")
    assert [u["name"] for u in admin.get("/api/team/users").json()] == ["root", "sam"]
    assert admin.put("/api/team/users/eve", json={"password": PW}).status_code == 200


def test_pc_only_actions_stay_on_the_pc_for_everyone(env):
    make("root", "admin")
    admin, _ = sign_in("root")
    assert admin.post("/api/library/folder/open").status_code == 403


def test_team_mode_off_means_no_sign_in(env, monkeypatch):
    monkeypatch.delenv("LET_TEAM")
    assert remote().post("/api/team/login", json={"name": "x", "password": PW}).status_code in (403, 404)
