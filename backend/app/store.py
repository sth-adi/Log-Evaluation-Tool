"""On-disk storage: one folder per imported source (Parquet data + JSON metadata).

Everything lives under LET_DATA_DIR (default: <repo>/data). Nothing here ever
talks to a vehicle; logs are only read from files the user imports.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from .downsample import minmax_downsample

REPO_ROOT = Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    d = Path(os.environ.get("LET_DATA_DIR", REPO_ROOT / "data"))
    (d / "sources").mkdir(parents=True, exist_ok=True)
    return d


_lock = threading.Lock()
_ID_RE = re.compile(r"^[0-9a-f]{10}$")


def _folder(source_id: str) -> Path:
    if not _ID_RE.match(source_id):
        raise KeyError(source_id)
    p = data_dir() / "sources" / source_id
    if not p.is_dir():
        raise KeyError(source_id)
    return p


def create_source(df: pd.DataFrame, meta: dict, label: str, kind: str, filename: str) -> dict:
    source_id = uuid.uuid4().hex[:10]
    folder = data_dir() / "sources" / source_id
    folder.mkdir(parents=True)
    df.to_parquet(folder / "data.parquet", index=False, row_group_size=65536)
    record = {
        "id": source_id,
        "label": label,
        "kind": kind,
        "filename": filename,
        "imported_at": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
        "offset_s": 0.0,
        **meta,
    }
    (folder / "meta.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def get_source(source_id: str) -> dict:
    return json.loads((_folder(source_id) / "meta.json").read_text(encoding="utf-8"))


def list_sources() -> list[dict]:
    out = []
    for p in sorted((data_dir() / "sources").iterdir()):
        if (p / "meta.json").exists():
            out.append(json.loads((p / "meta.json").read_text(encoding="utf-8")))
    out.sort(key=lambda r: r["imported_at"])
    return out


def update_source(source_id: str, **fields) -> dict:
    with _lock:
        rec = get_source(source_id)
        rec.update({k: v for k, v in fields.items() if v is not None})
        (_folder(source_id) / "meta.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
        return rec


def arrange_sources(mode: str, gap_s: float) -> list[dict]:
    """Set offsets so logs sit in session-start order.

    "sequential" lays them end to end (what LifeView's concatenated view does); "real" keeps the
    true wall-clock spacing between sessions. Logs with no known start time go after the others,
    in import order.
    """
    with _lock:
        recs = list_sources()
        dated = sorted((r for r in recs if r.get("started_at")), key=lambda r: r["started_at"])
        undated = [r for r in recs if not r.get("started_at")]
        t0 = datetime.fromisoformat(dated[0]["started_at"]) if dated else None
        cursor = 0.0
        for r in dated + undated:
            if mode == "real" and r.get("started_at"):
                off = (datetime.fromisoformat(r["started_at"]) - t0).total_seconds()
            else:
                off = cursor
            cursor = max(cursor, off + float(r["duration_s"]) + gap_s)
            r["offset_s"] = round(off, 6)
            (_folder(r["id"]) / "meta.json").write_text(json.dumps(r, indent=2), encoding="utf-8")
        return recs


def delete_source(source_id: str) -> None:
    shutil.rmtree(_folder(source_id))


def read_signals(
    source_id: str, channels: list[str], t0: float | None, t1: float | None, px: int
) -> dict:
    """Return downsampled channels for the window [t0, t1] (source-local seconds + offset)."""
    rec = get_source(source_id)
    offset = float(rec.get("offset_s", 0.0))
    known = {c["name"] for c in rec["channels"]}
    bad = [c for c in channels if c not in known]
    if bad:
        raise ValueError(f"unknown channel(s): {', '.join(bad)}")

    lo = (t0 if t0 is not None else -np.inf) - offset
    hi = (t1 if t1 is not None else np.inf) - offset
    cols = ", ".join(f'"{c}"' for c in channels)
    con = duckdb.connect()
    try:
        # one-sample margin is added in minmax_downsample, so over-fetch slightly
        pad = 2.0 / max(float(rec.get("sample_rate_hz") or 1.0), 1e-6)
        q = (
            f"SELECT time_s, {cols} FROM read_parquet(?) "
            "WHERE time_s >= ? AND time_s <= ? ORDER BY time_s"
        )
        arr = con.execute(
            q, [str(_folder(source_id) / "data.parquet"), lo - pad, hi + pad]
        ).fetchnumpy()
    finally:
        con.close()

    t = np.asarray(arr["time_s"], dtype=float)
    result: dict[str, dict] = {}
    full = True
    for c in channels:
        # DuckDB returns NULLs as a masked array; np.asarray would turn them into 0.0
        y = np.ma.filled(np.ma.asarray(arr[c], dtype=float), np.nan)
        tt, yy, is_full = minmax_downsample(t, y, lo, hi, max(px, 16))
        full = full and is_full
        result[c] = {"t": np.round(tt + offset, 6).tolist(), "v": yy.tolist()}
    return {"source_id": source_id, "offset_s": offset, "full_resolution": full, "channels": result}
