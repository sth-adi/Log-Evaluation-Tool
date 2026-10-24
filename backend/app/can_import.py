"""CAN logs: raw frames decoded with a DBC file into ordinary channels.

A CAN log holds frames (an id and up to 8 bytes). A DBC file says which signals are packed into each
id and how to scale them. Signals arrive at different rates, so they are put on one time base by
holding each value until the next frame of its message. A signal that stops arriving shows as a gap
rather than a flat line. Frames the DBC does not describe are counted and reported, never dropped
quietly.
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
import tempfile
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import store
from .importer import ImportErrorDetail, _build, _clean_name, _raw_sha

CAN_EXTENSIONS = {".asc", ".blf", ".trc"}
MAX_CELLS = 20_000_000  # rows x channels kept after putting signals on one time base
MIN_RASTER_S, MAX_RASTER_S = 0.002, 1.0


# --- the library of DBC files ---------------------------------------------------------------------


def _dir() -> Path:
    d = store.data_dir() / "dbc"
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_dbc() -> list[dict]:
    index = _dir() / "index.json"
    return json.loads(index.read_text(encoding="utf-8")) if index.is_file() else []


def _write_index(entries: list[dict]) -> None:
    (_dir() / "index.json").write_text(json.dumps(entries, indent=2), encoding="utf-8")


def _parse_dbc(raw: bytes):
    import cantools

    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")  # DBC files from Windows tools are often not UTF-8
    try:
        return cantools.database.load_string(text, database_format="dbc")
    except cantools.database.errors.Error as e:
        raise ValueError(f"That is not a readable DBC file: {e}") from e


def add_dbc(name: str, raw: bytes) -> dict:
    """Validate and keep a DBC file. The same file added twice is kept once."""
    db = _parse_dbc(raw)
    if not db.messages:
        raise ValueError("That DBC file defines no messages")
    sha = hashlib.sha256(raw).hexdigest()
    entries = list_dbc()
    for e in entries:
        if e["sha"] == sha:
            return e
    entry = {
        "id": uuid.uuid4().hex[:10],
        "name": (name.strip() or "DBC file")[:80],
        "sha": sha,
        "messages": len(db.messages),
        "signals": sum(len(m.signals) for m in db.messages),
        "added": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (_dir() / f"{entry['id']}.dbc").write_bytes(raw)
    _write_index([*entries, entry])
    return entry


def delete_dbc(dbc_id: str) -> None:
    entries = list_dbc()
    if not any(e["id"] == dbc_id for e in entries):
        raise KeyError(dbc_id)
    (_dir() / f"{dbc_id}.dbc").unlink(missing_ok=True)
    _write_index([e for e in entries if e["id"] != dbc_id])


def _load(ids: list[str]) -> list[tuple[str, object]]:
    known = {e["id"]: e for e in list_dbc()}
    out = []
    for i in ids:
        if i not in known:
            raise ImportErrorDetail(f"The DBC file {i} is not in your library any more")
        out.append((known[i]["name"], _parse_dbc((_dir() / f"{i}.dbc").read_bytes())))
    return out


# --- reading a log ---------------------------------------------------------------------------------


def parse_can(raw: bytes, filename: str, dbc_ids: list[str], profile: dict | None = None):
    import can
    import cantools

    profile = profile or {}
    if not dbc_ids:
        raise ImportErrorDetail("Choose the DBC file that describes this CAN log. It says what each frame means.")
    dbs = _load(dbc_ids)
    by_id: dict[tuple[int, bool], object] = {}
    for _name, db in dbs:
        for m in db.messages:
            by_id.setdefault((m.frame_id, bool(m.is_extended_frame)), m)

    ext = os.path.splitext(filename.lower())[1]
    times: dict[tuple[str, str], list[float]] = {}
    values: dict[tuple[str, str], list[float]] = {}
    unknown: Counter[int] = Counter()
    undecodable: Counter[str] = Counter()
    total = errors = 0
    first_ts: float | None = None
    last_ts = 0.0

    # python-can leaves a file open when a reader fails to start, which Windows will not let us delete
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        path = os.path.join(tmp, "in" + ext)
        with open(path, "wb") as f:
            f.write(raw)
        try:
            with can.LogReader(path) as reader:
                for msg in reader:
                    total += 1
                    if first_ts is None:
                        first_ts = msg.timestamp
                    last_ts = msg.timestamp
                    if msg.is_error_frame or msg.is_remote_frame:
                        errors += 1
                        continue
                    m = by_id.get((msg.arbitration_id, bool(msg.is_extended_id)))
                    if m is None:
                        unknown[msg.arbitration_id] += 1
                        continue
                    try:
                        decoded = m.decode(bytes(msg.data), decode_choices=False, scaling=True)
                    except cantools.database.errors.DecodeError:
                        undecodable[m.name] += 1
                        continue
                    for sig, v in decoded.items():
                        key = (m.name, sig)
                        times.setdefault(key, []).append(msg.timestamp)
                        values.setdefault(key, []).append(float(v))
        except (can.CanError, ValueError, OSError, EOFError, struct.error, NotImplementedError) as e:  # what the readers raise for a damaged file
            raise ImportErrorDetail(f"Could not read the file as a CAN log: {e}") from e

    if not total:
        raise ImportErrorDetail("The CAN log has no frames")
    if not times:
        ids = ", ".join(f"0x{i:X}" for i, _ in unknown.most_common(6))
        raise ImportErrorDetail(f"None of the {total:,} frames matched a message in the DBC file. The log uses ids such as {ids or 'none'}; is this the right DBC?")

    # one column per signal, prefixed with its message only where the same name appears twice
    name_count = Counter(sig for _, sig in times)
    columns = {key: _clean_name(key[1] if name_count[key[1]] == 1 else f"{key[0]}_{key[1]}") for key in times}
    info = {(m.name, s.name): s for m in {mm for mm in by_id.values()} for s in m.signals}

    duration = max(last_ts - first_ts, 1e-9)
    periods = [float(np.median(np.diff(t))) for t in times.values() if len(t) > 2]
    fastest = min((p for p in periods if p > 0), default=0.01)
    raster = float(profile.get("raster_s") or 0) or min(max(fastest, MIN_RASTER_S), MAX_RASTER_S)
    capped = False
    if duration / raster * len(times) > MAX_CELLS:
        raster, capped = duration * len(times) / MAX_CELLS, True
    grid = np.arange(0.0, duration + raster / 2, raster)

    data: dict[str, np.ndarray] = {"time_s": grid}
    for key, ts in times.items():
        t = np.asarray(ts) - first_ts
        v = np.asarray(values[key])
        order = np.argsort(t, kind="stable")
        t, v = t[order], v[order]
        period = float(np.median(np.diff(t))) if len(t) > 2 else 1.0
        idx = np.searchsorted(t, grid, side="right") - 1
        live = idx >= 0
        age = grid - t[np.maximum(idx, 0)]
        data[columns[key]] = np.where(live & (age <= max(10 * period, 0.5)), v[np.maximum(idx, 0)], np.nan)
    df = pd.DataFrame(data)

    units = {columns[k]: (info[k].unit or "") for k in times}
    states = {
        columns[k]: {str(int(val)): str(label) for val, label in info[k].choices.items()}
        for k in times
        if info[k].choices
    }
    names = " and ".join(n for n, _ in dbs)
    assumptions = [
        f"decoded {total - sum(unknown.values()) - errors - sum(undecodable.values()):,} of {total:,} CAN frames using {names}",
        f"put on one time base every {raster:g} s, holding each value until its next frame (a signal silent for ten of its own periods shows as a gap)",
    ]
    warnings: list[str] = []
    if capped:
        warnings.append(f"the log is long, so the time base was coarsened to {raster:g} s to keep it a workable size")
    if unknown:
        top = ", ".join(f"0x{i:X} ({n:,})" for i, n in unknown.most_common(6))
        warnings.append(f"{sum(unknown.values()):,} frame(s) with ids the DBC does not describe were ignored: {top}")
    if undecodable:
        warnings.append("frames with the wrong length for their message were ignored: " + ", ".join(f"{m} ({n:,})" for m, n in undecodable.most_common(6)))
    if errors:
        warnings.append(f"{errors:,} error or remote frame(s) were ignored")

    started = datetime.fromtimestamp(first_ts).strftime("%Y-%m-%d %H-%M-%S") if first_ts > 1e9 else ""  # absolute time only
    sha = hashlib.sha256((_raw_sha(raw) + "|" + "|".join(sorted(dbc_ids))).encode()).hexdigest()
    parsed = _build(df, units, assumptions, warnings, {**profile, "time_column": "time_s", "time_unit": "s"}, sha, started, filename)
    for ch in parsed.meta["channels"]:
        if ch["name"] in states:
            ch["states"] = states[ch["name"]]
    return parsed
