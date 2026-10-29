"""Opening the tool to a phone on the same Wi-Fi, safely.

By default the server only answers this PC. Phone access is opt-in: start it with LET_LAN=1 (the
"Log Evaluation Tool (phone).bat" launcher does) and it listens on the network, but:

* a device that is not this PC must carry the sharing key, in a cookie. The PC shows a link and a QR
  code containing the key; opening it once sets the cookie and the key leaves the address bar;
* things that act on this PC (converting .LRD logs by driving LifeView, opening Explorer, opening
  serial ports or UDP sockets for live data) answer this PC only, key or not;
* with sharing off, any request from another device is refused outright, even if the server was
  started listening on every interface by mistake.

Nothing here makes the tool safe to put on the internet or a network you do not trust: the key is
sent over plain HTTP.
"""

from __future__ import annotations

import hmac
import ipaddress
import os
import secrets
import socket
from http.cookies import SimpleCookie
from urllib.parse import parse_qsl, urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

from . import store

COOKIE = "let_key"
ONE_YEAR = 365 * 24 * 3600

router = APIRouter()


def sharing_enabled() -> bool:
    return os.environ.get("LET_LAN") == "1" or os.environ.get("LET_TEAM") == "1"


def team_enabled() -> bool:
    return os.environ.get("LET_TEAM") == "1"


# A reverse proxy or tunnel on this PC reaches the tool from 127.0.0.1, so its requests must not
# count as the PC itself. Proxies say who the real caller is in one of these headers.
PROXY_HEADERS = (b"x-forwarded-for", b"forwarded", b"x-real-ip", b"cf-connecting-ip", b"x-forwarded-host", b"true-client-ip")


def proxied(headers) -> bool:
    names = {k.lower() if isinstance(k, bytes) else k.lower().encode() for k, _ in headers}
    return any(h in names for h in PROXY_HEADERS)


def is_loopback(host: str | None) -> bool:
    if not host:
        return False
    try:
        return ipaddress.ip_address(host.split("%")[0]).is_loopback
    except ValueError:
        return False


def is_local(request: Request) -> bool:
    """True when the request comes from the PC that runs the tool."""
    return is_loopback(request.client.host if request.client else None) and not proxied(request.scope["headers"])


def require_local(request: Request) -> None:
    """Dependency for endpoints that act on this PC. Phones, even with the key, get a clear refusal."""
    if not is_local(request):
        raise HTTPException(403, "This only works on the PC that runs the tool.")


# --- the sharing key ----------------------------------------------------------------------------

_cache: dict[str, str] = {}


def _key_file():
    return store.data_dir() / "share_key.txt"


def key() -> str:
    """The sharing key, made on first use and kept so a phone stays signed in across restarts."""
    path = _key_file()
    cached = _cache.get(str(path))
    if cached:
        return cached
    if path.is_file():
        value = path.read_text(encoding="utf-8").strip()
        if len(value) >= 16:
            _cache[str(path)] = value
            return value
    return reset_key()


def reset_key() -> str:
    """A new key. Every phone that was signed in with the old one is signed out."""
    path = _key_file()
    value = secrets.token_urlsafe(16)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(value)
    _cache[str(path)] = value
    return value


def _same(a: str | None, b: str) -> bool:
    return bool(a) and hmac.compare_digest(a.encode(), b.encode())


# --- finding this PC's address on the network ---------------------------------------------------


TAILSCALE = ipaddress.ip_network("100.64.0.0/10")  # addresses on a Tailscale network


def usable_addresses(candidates: list[str]) -> list[str]:
    """Private network addresses only, in the order given, without repeats."""
    out: list[str] = []
    for ip in candidates:
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if a.version != 4 or not (a.is_private or a in TAILSCALE) or a.is_loopback or a.is_link_local or ip in out:
            continue
        out.append(ip)
    return out


def lan_addresses() -> list[str]:
    """This PC's addresses a phone on the same network could use, the main one first."""
    found: list[str] = []
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:  # no packet is sent: this only asks the OS which interface it would use
        probe.connect(("10.255.255.255", 1))
        found.append(probe.getsockname()[0])
    except OSError:
        pass
    finally:
        probe.close()
    try:
        found += [str(i[4][0]) for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
    except OSError:
        pass
    return usable_addresses(found)


# --- the gate -----------------------------------------------------------------------------------

_PAGE = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Log Evaluation Tool</title>
<body style="margin:0;display:grid;place-items:center;min-height:100vh;background:#0a0b0d;color:#eceef2;font:16px/1.5 system-ui,sans-serif">
<main style="max-width:30rem;padding:24px"><h1 style="font-size:22px;margin:0 0 12px">{title}</h1><p style="color:#8b919c;margin:0">{text}</p></main>
</body></html>"""


async def _refuse(scope, send, status: int, title: str, text: str) -> None:
    if scope["type"] == "websocket":
        await send({"type": "websocket.close", "code": 1008})
        return
    if scope["path"].startswith("/api"):
        body, ctype = ('{"detail":"%s"}' % text.replace('"', "'")).encode(), b"application/json"
    else:
        body, ctype = _PAGE.format(title=title, text=text).encode(), b"text/html; charset=utf-8"
    await send(
        {"type": "http.response.start", "status": status, "headers": [(b"content-type", ctype), (b"cache-control", b"no-store")]}
    )
    await send({"type": "http.response.body", "body": body})


class AccessMiddleware:
    """Lets this PC through; lets other devices through only with sharing on and the key."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        client = scope.get("client")
        if is_loopback(client[0] if client else None) and not proxied(scope["headers"]):
            return await self.app(scope, receive, send)

        if not sharing_enabled():
            return await _refuse(
                scope, send, 403, "Phone access is off",
                "This tool is only open on the PC it runs on. On that PC, start it with "
                "'Log Evaluation Tool (phone).bat' to open it to your phone.",
            )
        if scope["type"] == "websocket":
            return await _refuse(scope, send, 403, "", "")

        headers = {k.lower(): v for k, v in scope["headers"]}
        if team_enabled():
            return await self._team(scope, receive, send, headers)
        expected = key()
        jar = SimpleCookie()
        try:
            jar.load(headers.get(b"cookie", b"").decode("latin-1"))
        except Exception:  # a broken cookie header is the same as no cookie
            jar = SimpleCookie()
        if COOKIE in jar and _same(jar[COOKIE].value, expected):
            return await self.app(scope, receive, send)

        query = parse_qsl(scope.get("query_string", b"").decode("latin-1"), keep_blank_values=True)
        given = next((v for k, v in query if k == "key"), None)
        if _same(given, expected):
            if scope["method"] != "GET":
                return await self.app(scope, receive, send)
            rest = [(k, v) for k, v in query if k != "key"]
            where = scope["path"] + (("?" + urlencode(rest)) if rest else "")
            cookie = f"{COOKIE}={expected}; Path=/; Max-Age={ONE_YEAR}; HttpOnly; SameSite=Lax"
            await send(
                {
                    "type": "http.response.start",
                    "status": 303,
                    "headers": [(b"location", where.encode()), (b"set-cookie", cookie.encode()), (b"cache-control", b"no-store")],
                }
            )
            return await send({"type": "http.response.body", "body": b""})

        await _refuse(
            scope, send, 401, "Open this tool from the link on the PC",
            "On the PC, open Log Evaluation Tool, choose More, then Open on phone, and scan the code with this phone.",
        )


    async def _team(self, scope, receive, send, headers):
        """Team mode: other devices sign in with an account instead of using the sharing key."""
        from . import team

        who = team.user_for_token(team.token_from_cookie_header(headers.get(b"cookie", b"")))
        if who:
            scope.setdefault("state", {})["team_user"] = who
            return await self.app(scope, receive, send)
        if scope["method"] == "POST" and scope["path"] == "/api/team/login":
            return await self.app(scope, receive, send)
        if scope["path"].startswith("/api"):
            return await _refuse(scope, send, 401, "", "Sign in first.")
        body = _SIGN_IN.encode()
        await send(
            {"type": "http.response.start", "status": 401, "headers": [(b"content-type", b"text/html; charset=utf-8"), (b"cache-control", b"no-store")]}
        )
        await send({"type": "http.response.body", "body": body})


_SIGN_IN = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Sign in</title>
<body style="margin:0;display:grid;place-items:center;min-height:100vh;background:#0a0b0d;color:#eceef2;font:16px/1.5 system-ui,sans-serif">
<form id="f" style="width:min(22rem,90vw);display:grid;gap:12px;padding:24px">
<h1 style="font-size:22px;margin:0">Log Evaluation Tool</h1>
<p style="color:#8b919c;margin:0">Sign in with the name and password the team administrator made for you.</p>
<input id="n" autocomplete="username" placeholder="Name" required style="padding:10px;border-radius:6px;border:1px solid #2a2f38;background:#14171c;color:inherit;font:inherit">
<input id="p" type="password" autocomplete="current-password" placeholder="Password" required style="padding:10px;border-radius:6px;border:1px solid #2a2f38;background:#14171c;color:inherit;font:inherit">
<button style="padding:10px;border:0;border-radius:6px;background:#e53945;color:#fff;font:inherit;font-weight:600;cursor:pointer">Sign in</button>
<p id="e" role="alert" style="color:#ff8a92;margin:0;min-height:1.5em"></p></form>
<script>
document.getElementById("f").onsubmit = async (ev) => {
  ev.preventDefault();
  const r = await fetch("/api/team/login", {method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({name: document.getElementById("n").value, password: document.getElementById("p").value})});
  if (r.ok) return location.reload();
  document.getElementById("e").textContent = (await r.json()).detail || "Could not sign in.";
};
</script></body></html>"""


# --- endpoints ----------------------------------------------------------------------------------


@router.get("/api/sharing", response_class=PlainTextResponse, include_in_schema=False)
def sharing_text() -> str:
    """Plain text so the launcher can check it without parsing JSON."""
    return ("sharing-on" + (" team-on" if team_enabled() else "")) if sharing_enabled() else "sharing-off"


@router.get("/api/share")
def share_info(request: Request) -> dict:
    """Links for the phone. Only the PC itself can ask, since the links contain the key."""
    require_local(request)
    if not sharing_enabled():
        return {"enabled": False}
    port = request.url.port or 80
    if team_enabled():  # teammates sign in with an account, so the address carries no key
        return {"enabled": True, "port": port, "urls": [f"http://{ip}:{port}/" for ip in lan_addresses()]}
    k = key()
    return {"enabled": True, "port": port, "urls": [f"http://{ip}:{port}/?key={k}" for ip in lan_addresses()]}


@router.post("/api/share/reset")
def share_reset(request: Request) -> dict:
    """New key: phones that were signed in with the old link stop working."""
    require_local(request)
    if not sharing_enabled():
        raise HTTPException(409, "Phone access is off.")
    reset_key()
    return share_info(request)
