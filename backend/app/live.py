"""Live telemetry: a hub that holds the latest samples, adapters that feed it, and the API around it.

Data reaches the hub one of five ways, all ending in ``Hub.push_block``:

* ``push``      another program (a CAN or radio bridge) POSTs rows to /api/live/ingest
* ``udp``       datagrams of JSON lines, or CSV lines with a header row, on a local port
* ``serial``    the same line formats over a COM port (needs pyserial)
* ``replay``    a log already in the library, played back in real time (for demos and testing)
* ``simulator`` a made-up car lapping a circuit, so the whole screen can be tried with no car

The browser follows the hub over Server-Sent Events. "Save as log" turns what the hub holds into an
ordinary log, so lap analysis, reports and downloads work on a recorded session like any other.

A line is either a JSON object ``{"t": 12.34, "rpm": 8500, "vehicleSpeed": 71.2}`` (``t`` optional,
seconds; missing means "now") or CSV where the first non-numeric line names the columns.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import socket
import threading
import time
import uuid
from collections import deque
from datetime import datetime

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from . import store
from .access import require_local
from .importer import _guess_unit

log = logging.getLogger(__name__)

CAPACITY = int(os.environ.get("LET_LIVE_ROWS", 200_000))
MAX_CHANNELS = 400
MAX_BATCH = 20_000


class LiveError(ValueError):
    """Something the person can fix (bad port, nothing to save). Shown as is."""


class BadLine(ValueError):
    """A line that was meant as data but cannot be read. It is counted and shown, never dropped quietly."""


def _number(key: str, v) -> float:
    if v is None:
        return float("nan")  # a sample that is missing is not an error
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise BadLine(f"'{key}' is not a number ({v!r})")
    return float(v)


def parse_line(line: str, state: dict) -> dict | None:
    """One text line to ``{"t": float|None, "values": {name: float}}``.

    Returns None for a blank line or a CSV header line (which sets the column names in ``state`` for the
    lines that follow). Raises BadLine for anything else that is not data.
    """
    line = line.strip()
    if not line:
        return None
    if line[0] in "{[":
        try:
            obj = json.loads(line)
        except ValueError as e:
            raise BadLine(f"not valid JSON: {e}") from e
        if not isinstance(obj, dict):
            raise BadLine("a JSON line must be an object like {\"rpm\": 8000}")
        t = obj.pop("t", None)
        vals = {str(k): _number(k, v) for k, v in obj.items()}
        if not vals:
            raise BadLine("the line has no channels")
        return {"t": None if t is None else _number("t", t), "values": vals}
    parts = [p.strip() for p in line.replace(";", ",").replace("\t", ",").split(",")]
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        if any(not p or any(c in p for c in "{}[]\"'") for p in parts):
            raise BadLine("not a data line, and not a header naming plain columns")
        state["header"] = parts  # a line of plain names, not numbers, names the columns
        return None
    header = state.get("header")
    if not header:
        raise BadLine("numbers arrived before a header line naming the columns")
    if len(header) != len(nums):
        raise BadLine(f"{len(nums)} values for {len(header)} columns")
    vals = dict(zip(header, nums))
    t = vals.pop(next((h for h in header if h.lower() in ("t", "time", "time_s", "timestamp")), ""), None)
    if not vals:
        raise BadLine("the line has only a time column")
    return {"t": t, "values": vals}


class Hub:
    """The latest samples, in a ring buffer that never grows past ``capacity`` rows."""

    def __init__(self, capacity: int = CAPACITY):
        self.cap = capacity
        self.lock = threading.RLock()
        self._runner: threading.Thread | None = None
        self._stop = threading.Event()
        self.source: dict | None = None
        self.error: str | None = None
        self.clear()

    # --- the buffer -------------------------------------------------------------------------

    def clear(self) -> None:
        with self.lock:
            self.n = 0  # rows pushed since the last clear
            self.t = np.full(self.cap, np.nan)
            self.cols: dict[str, np.ndarray] = {}
            self.units: dict[str, str] = {}
            self.started_wall: datetime | None = None
            self._mono0: float | None = None
            self._marks: deque[tuple[float, int]] = deque()
            self.last_push = 0.0
            self.rejected = 0  # lines a source sent that could not be read
            self.last_reject: str | None = None

    def push_block(self, t: np.ndarray | None, cols: dict[str, np.ndarray], units: dict[str, str] | None = None) -> int:
        """Append k rows. ``t`` None stamps them with the time since the first row arrived."""
        k = len(next(iter(cols.values()))) if cols else 0
        if k == 0:
            return 0
        if k > self.cap:  # keep only what fits
            cols = {c: v[-self.cap :] for c, v in cols.items()}
            t = None if t is None else t[-self.cap :]
            k = self.cap
        now = time.monotonic()
        with self.lock:
            if self.started_wall is None:
                self.started_wall = datetime.now()
                self._mono0 = now
            if t is None:
                t = np.full(k, now - self._mono0)
            idx = (self.n + np.arange(k)) % self.cap
            self.t[idx] = t
            for name in cols:
                if name not in self.cols and len(self.cols) < MAX_CHANNELS:
                    self.cols[name] = np.full(self.cap, np.nan, dtype=np.float32)
            for name, col in self.cols.items():
                col[idx] = cols[name] if name in cols else np.nan
            for name, u in (units or {}).items():
                self.units[name] = u
            self.n += k
            self.last_push = now
            self._marks.append((now, self.n))
            while len(self._marks) > 2 and now - self._marks[0][0] > 3.0:
                self._marks.popleft()
        return k

    def reject(self, why: str) -> None:
        with self.lock:
            self.rejected += 1
            self.last_reject = why

    def push_rows(self, rows: list[dict], units: dict[str, str] | None = None) -> int:
        """Rows as ``{"t": seconds|None, "values": {name: value}}``."""
        rows = [r for r in rows if r.get("values")][:MAX_BATCH]
        if not rows:
            return 0
        names = list(dict.fromkeys(n for r in rows for n in r["values"]))
        cols = {n: np.array([r["values"].get(n, np.nan) for r in rows], dtype=np.float32) for n in names}
        stamped = [r.get("t") for r in rows]
        t = None if any(x is None for x in stamped) else np.array(stamped, dtype=float)
        return self.push_block(t, cols, units)

    def rows_since(self, seq: int, names: list[str], limit: int = 5000) -> tuple[int, int, np.ndarray, dict[str, np.ndarray]]:
        """New rows after ``seq``: (next seq, rows dropped because the reader fell behind, t, columns)."""
        with self.lock:
            lo = max(seq, self.n - self.cap)
            dropped = max(0, min(lo, self.n) - seq) if seq < self.n else 0
            if self.n - lo > limit:  # a slow reader skips ahead rather than lagging further
                dropped += (self.n - lo) - limit
                lo = self.n - limit
            idx = np.arange(lo, self.n) % self.cap
            return (
                self.n,
                dropped,
                self.t[idx].copy(),
                {c: self.cols[c][idx].astype(float) for c in names if c in self.cols},
            )

    def window(self, names: list[str], seconds: float, points: int = 600) -> tuple[np.ndarray, dict[str, np.ndarray]]:
        """The last ``seconds`` of data, thinned to about ``points`` rows, for the first paint."""
        with self.lock:
            if self.n == 0:
                return np.array([]), {}
            have = min(self.n, self.cap)
            idx = (np.arange(self.n - have, self.n)) % self.cap
            t = self.t[idx]
            keep = t >= t[-1] - seconds
            idx, t = idx[keep], t[keep]
            if len(idx) > points:
                pick = np.linspace(0, len(idx) - 1, points).astype(int)
                idx, t = idx[pick], t[pick]
            return t.copy(), {c: self.cols[c][idx].astype(float) for c in names if c in self.cols}

    def status(self) -> dict:
        with self.lock:
            now = time.monotonic()
            rate = None
            if len(self._marks) >= 2 and self._marks[-1][0] > self._marks[0][0]:
                (m0, n0), (m1, n1) = self._marks[0], self._marks[-1]
                rate = (n1 - n0) / (m1 - m0)
            last = self.n - 1
            channels = []
            for name, col in self.cols.items():
                v = col[last % self.cap] if self.n else np.nan
                channels.append({"name": name, "unit": self.units.get(name) or _guess_unit(name), "last": None if not np.isfinite(v) else float(v)})
            running = self._runner is not None and self._runner.is_alive()
            return {
                "state": "running" if running else "stopped",
                "source": self.source,
                "error": self.error,
                "rejected": self.rejected,
                "last_reject": self.last_reject,
                "rows": self.n,
                "kept": min(self.n, self.cap),
                "capacity": self.cap,
                "rate_hz": None if rate is None else round(rate, 1),
                "age_s": None if not self.n else round(now - self.last_push, 2),
                "time_s": None if not self.n else float(self.t[last % self.cap]),
                "channels": channels,
            }

    # --- adapters ---------------------------------------------------------------------------

    def start(self, kind: str, options: dict | None = None, keep: bool = False) -> dict:
        options = options or {}
        targets = {"simulator": _run_simulator, "replay": _run_replay, "udp": _run_udp, "serial": _run_serial, "push": None}
        if kind not in targets:
            raise LiveError(f"unknown live source {kind!r}")
        self.stop()
        if not keep:
            self.clear()
        self.error = None
        self.source = {"kind": kind, "label": _label(kind, options), "options": options}
        if targets[kind] is None:  # nothing to run: a bridge will POST rows
            return self.status()
        # fail now, with a message, rather than inside a thread nobody is watching
        if kind == "replay":
            _replay_arrays(options)
        if kind == "serial":
            _open_serial(options).close()
        self._stop = threading.Event()
        self._runner = threading.Thread(target=self._guard, args=(targets[kind], options, self._stop), daemon=True, name=f"live-{kind}")
        self._runner.start()
        return self.status()

    def _guard(self, fn, options, stop) -> None:
        try:
            fn(self, options, stop)
        except Exception as e:  # a thread nobody joins: the message goes to the Live screen, the traceback to the log
            log.exception("live source %s failed", self.source and self.source.get("kind"))
            self.error = str(e) or e.__class__.__name__

    def stop(self) -> None:
        self._stop.set()
        r = self._runner
        if r and r.is_alive() and r is not threading.current_thread():
            r.join(timeout=3)
        self._runner = None

    # --- recording --------------------------------------------------------------------------

    def save(self, label: str) -> dict:
        """What the hub holds, stored as an ordinary log in the library."""
        with self.lock:
            if self.n < 20:
                raise LiveError("Nothing to save yet. Wait for some live data first.")
            have = min(self.n, self.cap)
            idx = (np.arange(self.n - have, self.n)) % self.cap
            t = self.t[idx]
            df = pd.DataFrame({"time_s": t - t[0]})
            for name, col in self.cols.items():
                v = col[idx].astype(float)
                if np.isfinite(v).any():
                    df[name] = v
            started = self.started_wall
            units = dict(self.units)
            wrapped = self.n > self.cap
            source = self.source or {}
        dts = np.diff(df["time_s"].to_numpy())
        med = float(np.median(dts)) if len(dts) else 0.0
        meta = {
            "content_sha": uuid.uuid4().hex,  # a live session is never a duplicate of an earlier one
            "started_at": (started or datetime.now()).replace(microsecond=0).isoformat(),
            "rows": int(len(df)),
            "channels": [
                {"name": c, "unit": units.get(c) or _guess_unit(c), "min": float(np.nanmin(df[c])), "max": float(np.nanmax(df[c]))}
                for c in df.columns
                if c != "time_s"
            ],
            "duration_s": float(df["time_s"].iloc[-1]),
            "sample_rate_hz": round(1.0 / med, 3) if med > 0 else None,
            "gaps": int((dts > 5 * med).sum()) if med > 0 else 0,
            "time_origin_raw": 0.0,
            "time_column": "time_s",
            "time_unit": "s",
            "assumptions": [f"recorded live ({source.get('label', 'unknown source')})"],
            "warnings": [f"the live buffer holds {self.cap:,} rows, so the start of a longer session was dropped"] if wrapped else [],
        }
        name = label.strip() or f"Live {meta['started_at'][11:19]}"
        return store.create_source(df, meta, name, "other", "live-session")


def _label(kind: str, o: dict) -> str:
    return {
        "simulator": "Simulated car",
        "replay": f"Replay of {o.get('label') or 'a saved log'}",
        "udp": f"UDP port {o.get('port', 5005)}",
        "serial": f"{o.get('port', 'serial port')} at {o.get('baud', 115200)} baud",
        "push": "Data pushed by another program",
    }[kind]


HUB = Hub()


# --- simulator ----------------------------------------------------------------------------------


def _run_simulator(hub: Hub, o: dict, stop: threading.Event) -> None:
    speed = max(float(o.get("speed", 1.0)), 0.1)
    hz = 100.0
    straight, radius = 160.0, 45.0
    length = 2 * straight + 2 * math.pi * radius
    rng = np.random.default_rng(o.get("seed"))
    s, lap_t, last_lap, lap_no, pace = 0.0, 0.0, 0.0, 0, 0.7  # lap 0 is a slow out-lap
    v_prev, t, ect = 0.0, 0.0, 70.0
    units = {"vehicleSpeed": "km/h", "rpm": "rpm", "tps1": "%", "latG": "g", "longG": "g", "gear": "", "lapTime": "s", "lastLapTime": "s", "ect1": "°C"}
    start = time.monotonic()
    while not stop.is_set():
        target = (time.monotonic() - start) * speed
        rows = {k: [] for k in ("t", *units)}
        while t < target and len(rows["t"]) < 5000:
            corner = straight <= s % length < straight + math.pi * radius or s % length >= 2 * straight + math.pi * radius
            v = pace * (15.0 if corner else 52.0)
            v += rng.normal(0, 0.15)
            curvature = 1.0 / radius if corner else 0.0
            acc = (v - v_prev) * hz
            v_prev = v
            ect += (95.0 - ect) * 0.0004
            for k, val in (
                ("t", t),
                ("vehicleSpeed", v * 3.6),
                ("rpm", 2500 + v * 75 + rng.normal(0, 25)),
                ("tps1", 18.0 if corner else min(100.0, v / (52 * pace) * 100)),
                ("latG", v * v * curvature / 9.80665),
                ("longG", acc / 9.80665),
                ("gear", float(min(6, int(v / 9) + 1))),
                ("lapTime", lap_t),
                ("lastLapTime", last_lap),
                ("ect1", ect + rng.normal(0, 0.05)),
            ):
                rows[k].append(val)
            s += v / hz
            lap_t += 1 / hz
            t += 1 / hz
            if s >= (lap_no + 1) * length:
                last_lap, lap_t, lap_no = lap_t, 0.0, lap_no + 1
                pace = float(rng.uniform(0.97, 1.04))
        if rows["t"]:
            hub.push_block(np.array(rows.pop("t")), {k: np.array(v, dtype=np.float32) for k, v in rows.items()}, units)
        stop.wait(0.05)


# --- replay -------------------------------------------------------------------------------------


def _replay_arrays(o: dict) -> tuple[np.ndarray, dict[str, np.ndarray], dict[str, str], dict]:
    sid = o.get("source_id")
    if not sid:
        raise LiveError("Choose a log to replay")
    try:
        rec = store.get_source(sid)
    except (KeyError, FileNotFoundError):
        raise LiveError("That log is not in the library any more") from None
    names = [c["name"] for c in rec["channels"]]
    t, arr = store.read_window(sid, names, None, None)
    if t.size < 2:
        raise LiveError("That log has no samples to replay")
    t = t - float(rec.get("offset_s", 0.0))
    units = {c["name"]: c.get("unit", "") for c in rec["channels"]}
    return t - t[0], {n: arr[n].astype(np.float32) for n in names}, units, rec


def _run_replay(hub: Hub, o: dict, stop: threading.Event) -> None:
    t, cols, units, rec = _replay_arrays(o)
    o.setdefault("label", rec["label"])
    hub.source = {**(hub.source or {}), "label": _label("replay", o)}
    speed = max(float(o.get("speed", 1.0)), 0.1)
    loop = bool(o.get("loop", False))
    span = float(t[-1] - t[0]) + float(np.median(np.diff(t)))
    i, cycle = 0, 0
    start = time.monotonic()
    while not stop.is_set():
        target = (time.monotonic() - start) * speed - cycle * span
        j = int(np.searchsorted(t, target, side="right"))
        if j > i:
            hub.push_block(t[i:j] + cycle * span, {n: c[i:j] for n, c in cols.items()}, units)
            i = j
        if i >= len(t):
            if not loop:
                return
            i, cycle = 0, cycle + 1
        stop.wait(0.04)


# --- UDP and serial -----------------------------------------------------------------------------


def _drain(hub: Hub, pending: list[dict]) -> None:
    if pending:
        hub.push_rows(pending)
        pending.clear()


def _run_udp(hub: Hub, o: dict, stop: threading.Event) -> None:
    port = int(o.get("port", 5005))
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((o.get("host", "0.0.0.0"), port))
    except OSError as e:
        raise LiveError(f"Could not listen on UDP port {port}: {e.strerror or e}") from e
    sock.settimeout(0.2)
    state: dict = {}
    pending: list[dict] = []
    last = time.monotonic()
    try:
        while not stop.is_set():
            try:
                data, _ = sock.recvfrom(65535)
                for line in data.decode("utf-8", "replace").splitlines():
                    try:
                        row = parse_line(line, state)
                    except BadLine as e:
                        hub.reject(str(e))
                        continue
                    if row:
                        pending.append(row)
            except socket.timeout:
                pass
            if pending and (len(pending) >= 200 or time.monotonic() - last > 0.05):
                _drain(hub, pending)
                last = time.monotonic()
    finally:
        sock.close()


def _open_serial(o: dict):
    try:
        import serial  # pyserial
    except ImportError as e:
        raise LiveError("Serial needs pyserial. Install it with: pip install pyserial") from e
    port = o.get("port")
    if not port:
        raise LiveError("Choose a serial port")
    try:
        return serial.Serial(port, int(o.get("baud", 115200)), timeout=0.2)
    except (OSError, serial.SerialException) as e:
        raise LiveError(f"Could not open {port}: {e}") from e


def list_ports() -> list[dict]:
    try:
        from serial.tools import list_ports as lp
    except ImportError:
        return []
    return [{"port": p.device, "description": p.description} for p in lp.comports()]


def _run_serial(hub: Hub, o: dict, stop: threading.Event) -> None:
    ser = _open_serial(o)
    state: dict = {}
    pending: list[dict] = []
    last = time.monotonic()
    try:
        while not stop.is_set():
            raw = ser.readline()
            if raw:
                try:
                    row = parse_line(raw.decode("utf-8", "replace"), state)
                except BadLine as e:
                    hub.reject(str(e))
                    continue
                if row:
                    pending.append(row)
            if pending and (len(pending) >= 200 or time.monotonic() - last > 0.05):
                _drain(hub, pending)
                last = time.monotonic()
    finally:
        ser.close()


# --- the API ------------------------------------------------------------------------------------

router = APIRouter(prefix="/api/live", tags=["live"])


class StartBody(BaseModel):
    source: str
    options: dict = {}
    keep: bool = False


class IngestBody(BaseModel):
    rows: list[dict]
    units: dict[str, str] = {}


class SaveBody(BaseModel):
    label: str = ""


@router.get("/status")
def live_status() -> dict:
    return HUB.status()


@router.get("/ports", dependencies=[Depends(require_local)])
def live_ports() -> list[dict]:
    return list_ports()


@router.post("/start", dependencies=[Depends(require_local)])
def live_start(body: StartBody) -> dict:
    try:
        return HUB.start(body.source, body.options, body.keep)
    except LiveError as e:
        raise HTTPException(422, str(e)) from e


@router.post("/stop", dependencies=[Depends(require_local)])
def live_stop() -> dict:
    HUB.stop()
    return HUB.status()


@router.post("/clear")
def live_clear() -> dict:
    HUB.clear()
    return HUB.status()


@router.post("/ingest")
def live_ingest(body: IngestBody) -> dict:
    """Rows from another program: ``{"rows": [{"t": 1.2, "values": {"rpm": 8000}}], "units": {...}}``."""
    rows = []
    for i, r in enumerate(body.rows[:MAX_BATCH]):
        vals = r.get("values", {k: v for k, v in r.items() if k != "t"})
        if not isinstance(vals, dict) or not vals:
            raise HTTPException(422, f"row {i}: no channel values")
        try:
            clean = {str(k): _number(k, v) for k, v in vals.items()}
            t = r.get("t")
            rows.append({"t": None if t is None else _number("t", t), "values": clean})
        except BadLine as e:
            raise HTTPException(422, f"row {i}: {e}") from e
    if HUB.source is None or not (HUB._runner and HUB._runner.is_alive()):
        # nothing of ours is feeding the hub, so these rows are a bridge's: say so
        HUB.source = {"kind": "push", "label": _label("push", {}), "options": {}}
    return {"accepted": HUB.push_rows(rows, body.units)}


@router.post("/save")
def live_save(body: SaveBody) -> dict:
    try:
        return HUB.save(body.label)
    except LiveError as e:
        raise HTTPException(422, str(e)) from e


@router.get("/window")
def live_window(channels: str = Query(...), seconds: float = Query(30, gt=0, le=3600), points: int = Query(600, ge=50, le=5000)) -> dict:
    names = [c for c in channels.split(",") if c][:40]
    t, cols = HUB.window(names, seconds, points)
    return {"t": t.tolist(), "v": {c: [None if not np.isfinite(x) else float(x) for x in v] for c, v in cols.items()}}


@router.get("/stream")
async def live_stream(request: Request, channels: str = Query(""), seq: int | None = None) -> StreamingResponse:
    """Server-Sent Events: new rows about ten times a second, plus a status line every second."""
    names = [c for c in channels.split(",") if c][:40]

    async def events():
        cursor = HUB.n if seq is None else seq
        sent_status = 0.0
        while not await request.is_disconnected():
            now = time.monotonic()
            nxt, dropped, t, cols = HUB.rows_since(cursor, names)
            body: dict = {}
            if len(t):
                body = {
                    "seq": nxt,
                    "dropped": dropped,
                    "t": t.tolist(),
                    "v": {c: [None if not np.isfinite(x) else float(x) for x in v] for c, v in cols.items()},
                }
            cursor = nxt
            if now - sent_status >= 1.0:
                body["status"] = HUB.status()
                sent_status = now
            if body:
                yield f"data: {json.dumps(body)}\n\n"
            else:
                yield ": keep-alive\n\n" if int(now) % 15 == 0 else ""
            await asyncio.sleep(0.1)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
