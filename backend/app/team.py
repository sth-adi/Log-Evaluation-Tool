"""Team accounts: named logins for the people who open the tool from their own computers.

Off by default. Start the tool with LET_TEAM=1 (the "Log Evaluation Tool (team).bat" launcher does)
and it listens on the network; then:

* the PC that runs the tool is always trusted, as an administrator. It makes the accounts;
* every other device must sign in with a name and password first. Without an account it gets a
  sign-in page, and nothing else;
* passwords are kept as scrypt hashes, never as text. Too many wrong tries lock the name out for a
  while. A sign-in lasts 30 days and ends when the account is deleted or the password changes;
* things that act on the PC itself (converting .LRD logs through LifeView, serial ports) still
  answer the PC only.

The library lives on the PC that runs the tool, so everyone who signs in sees the same logs, views
and findings. To reach it from outside the building, use a private network such as Tailscale: the
tool sends the sign-in over plain HTTP and must not be exposed to the internet directly.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from http.cookies import SimpleCookie

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from . import access, store

COOKIE = "let_session"
SESSION_S = 30 * 24 * 3600
MIN_PASSWORD = 10
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,31}$")
ROLES = ("admin", "member")
SCRYPT = (2**14, 8, 1)
MAX_TRIES = 5  # wrong passwords in a row ...
LOCK_S = 15 * 60  # ... lock that name from that address for this long

router = APIRouter()
_lock = threading.Lock()
_tries: dict[tuple[str, str], tuple[int, float]] = {}


def enabled() -> bool:
    return os.environ.get("LET_TEAM") == "1"


# --- passwords ----------------------------------------------------------------------------------


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    n, r, p = SCRYPT
    digest = hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=32)
    return f"scrypt${n}${r}${p}${salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, want = stored.split("$")
        got = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(got.hex(), want)
    except (ValueError, TypeError):
        return False


_DUMMY = hash_password("not a real password")  # so an unknown name takes as long as a wrong password


# --- accounts and sessions, kept beside the library --------------------------------------------


def _read(name: str, default):
    p = store.data_dir() / name
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else default


def _write(name: str, value) -> None:
    p = store.data_dir() / name
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(value, f, indent=1)


def users() -> dict[str, dict]:
    return _read("team_users.json", {})


def user_list() -> list[dict]:
    return [{"name": n, "role": u["role"], "created": u["created"]} for n, u in sorted(users().items(), key=lambda kv: kv[0].lower())]


def _find(name: str) -> str | None:
    return next((n for n in users() if n.lower() == name.lower()), None)


def _check_new(name: str, password: str | None, role: str | None) -> None:
    if not NAME.match(name):
        raise ValueError("A name is 2 to 32 letters, digits, dots, dashes or underscores, starting with a letter or digit.")
    if password is not None and len(password) < MIN_PASSWORD:
        raise ValueError(f"A password needs at least {MIN_PASSWORD} characters.")
    if role is not None and role not in ROLES:
        raise ValueError("The role is admin or member.")


def save_user(name: str, password: str | None, role: str | None) -> dict:
    """Make an account, or change an existing one's password or role. A password ends its sign-ins."""
    _check_new(name, password, role)
    with _lock:
        all_ = users()
        have = _find(name)
        if have is None:
            if password is None:
                raise ValueError("A new account needs a password.")
            all_[name] = {"hash": hash_password(password), "role": role or "member", "created": time.strftime("%Y-%m-%dT%H:%M:%S")}
        else:
            if password is not None:
                all_[have]["hash"] = hash_password(password)
                _end_sessions(have)
            if role is not None:
                all_[have]["role"] = role
            name = have
        _write("team_users.json", all_)
        return {"name": name, "role": all_[name]["role"], "created": all_[name]["created"]}


def delete_user(name: str) -> None:
    with _lock:
        all_ = users()
        have = _find(name)
        if have is None:
            raise KeyError(name)
        del all_[have]
        _write("team_users.json", all_)
        _end_sessions(have)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _end_sessions(name: str) -> None:
    s = _read("team_sessions.json", {})
    _write("team_sessions.json", {k: v for k, v in s.items() if v["user"] != name})


def new_session(name: str) -> str:
    token = secrets.token_urlsafe(32)
    with _lock:
        now = time.time()
        s = {k: v for k, v in _read("team_sessions.json", {}).items() if v["exp"] > now}
        s[_digest(token)] = {"user": name, "exp": now + SESSION_S}
        _write("team_sessions.json", s)
    return token


def end_session(token: str) -> None:
    with _lock:
        s = _read("team_sessions.json", {})
        if s.pop(_digest(token), None) is not None:
            _write("team_sessions.json", s)


def user_for_token(token: str | None) -> dict | None:
    """The account a session cookie belongs to, or None if it is unknown, expired or its account is gone."""
    if not token:
        return None
    rec = _read("team_sessions.json", {}).get(_digest(token))
    if not rec or rec["exp"] <= time.time():
        return None
    have = users().get(rec["user"])
    return {"name": rec["user"], "role": have["role"]} if have else None


def token_from_cookie_header(header: bytes | str) -> str | None:
    jar = SimpleCookie()
    try:
        jar.load(header.decode("latin-1") if isinstance(header, bytes) else header)
    except Exception:  # a broken cookie header is the same as no cookie
        return None
    return jar[COOKIE].value if COOKIE in jar else None


# --- signing in ----------------------------------------------------------------------------------


def _locked(key: tuple[str, str]) -> float:
    n, until = _tries.get(key, (0, 0.0))
    return max(until - time.time(), 0.0) if n >= MAX_TRIES else 0.0


def _failed(key: tuple[str, str]) -> None:
    n, until = _tries.get(key, (0, 0.0))
    if n >= MAX_TRIES and until <= time.time():
        n = 0  # the lock ran out
    _tries[key] = (n + 1, time.time() + LOCK_S)


class Login(BaseModel):
    name: str
    password: str


class NewUser(BaseModel):
    password: str | None = None
    role: str | None = None


def current(request: Request) -> dict | None:
    """The signed-in account for this request. The PC itself counts as an administrator."""
    if access.is_local(request):
        return {"name": "this PC", "role": "admin"}
    return request.scope.get("state", {}).get("team_user")


def require_admin(request: Request) -> dict:
    me = current(request)
    if not me or me["role"] != "admin":
        raise HTTPException(403, "Only an administrator can manage accounts.")
    return me


@router.get("/api/team/me")
def me(request: Request) -> dict:
    who = current(request)
    return {"team": enabled(), "user": who["name"] if who else None, "role": who["role"] if who else None, "local": access.is_local(request)}


@router.post("/api/team/login")
def login(body: Login, request: Request, response: Response) -> dict:
    if not enabled():
        raise HTTPException(404, "Team accounts are off.")
    ip = request.client.host if request.client else "?"
    key = (ip, body.name.lower())
    wait = _locked(key)
    if wait:
        raise HTTPException(429, f"Too many wrong passwords. Try again in {int(wait // 60) + 1} minutes.")
    have = _find(body.name)
    rec = users().get(have) if have else None
    ok = check_password(body.password, rec["hash"] if rec else _DUMMY) and rec is not None
    if not ok:
        _failed(key)
        raise HTTPException(401, "That name and password do not match.")
    _tries.pop(key, None)
    token = new_session(have)
    response.set_cookie(COOKIE, token, max_age=SESSION_S, httponly=True, samesite="strict", path="/")
    return {"user": have, "role": rec["role"]}


@router.post("/api/team/logout", status_code=204)
def logout(request: Request, response: Response) -> None:
    token = token_from_cookie_header(request.headers.get("cookie", ""))
    if token:
        end_session(token)
    response.delete_cookie(COOKIE, path="/")


@router.get("/api/team/users")
def list_users(request: Request) -> list[dict]:
    require_admin(request)
    return user_list()


@router.put("/api/team/users/{name}")
def put_user(name: str, body: NewUser, request: Request) -> dict:
    require_admin(request)
    try:
        return save_user(name, body.password, body.role)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@router.delete("/api/team/users/{name}", status_code=204)
def remove_user(name: str, request: Request) -> None:
    require_admin(request)
    try:
        delete_user(name)
    except KeyError:
        raise HTTPException(404, "unknown account") from None
