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

from . import derived as derived_mod
from . import events as events_mod
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


def create_source(
    df: pd.DataFrame, meta: dict, label: str, kind: str, filename: str, extra: dict | None = None
) -> dict:
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
        "open": True,  # in the current view; closed logs stay in the library
        **meta,
        **(extra or {}),
    }
    (folder / "meta.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record


def get_source(source_id: str) -> dict:
    return json.loads((_folder(source_id) / "meta.json").read_text(encoding="utf-8"))


def list_sources(include_closed: bool = False) -> list[dict]:
    """Logs in the current view (open ones), or every stored log with include_closed."""
    out = []
    for p in sorted((data_dir() / "sources").iterdir()):
        if (p / "meta.json").exists():
            out.append(json.loads((p / "meta.json").read_text(encoding="utf-8")))
    if not include_closed:
        out = [r for r in out if r.get("open", True)]
    out.sort(key=lambda r: r["imported_at"])
    return out


_backfilled: set[str] = set()


def _backfill_hashes() -> None:
    """Give logs imported before fingerprints existed one, from the CSV kept in exports."""
    from .importer import content_sha

    d = str(data_dir())
    if d in _backfilled:
        return
    _backfilled.add(d)
    for rec in list_sources(include_closed=True):
        kept = data_dir() / "exports" / rec.get("filename", "")
        if "content_sha" not in rec and rec.get("filename") and kept.is_file():
            try:
                update_source(rec["id"], content_sha=content_sha(kept.read_bytes()))
            except Exception:  # an unreadable copy just stays without a fingerprint
                pass


def find_existing(content_sha: str | None = None, lrd_sha: str | None = None) -> dict | None:
    """A stored log (open or closed) with the same data, so nothing is converted or stored twice."""
    _backfill_hashes()
    for rec in list_sources(include_closed=True):
        if (lrd_sha and rec.get("lrd_sha") == lrd_sha) or (content_sha and rec.get("content_sha") == content_sha):
            return rec
    return None


def library() -> list[dict]:
    """Every processed log, whether or not it is open, newest session first."""
    _backfill_hashes()
    out = []
    for rec in list_sources(include_closed=True):
        pq = data_dir() / "sources" / rec["id"] / "data.parquet"
        out.append(
            {
                "id": rec["id"],
                "label": rec["label"],
                "filename": rec.get("filename", ""),
                "started_at": rec.get("started_at"),
                "imported_at": rec["imported_at"],
                "duration_s": rec["duration_s"],
                "rows": rec["rows"],
                "channels": len(rec["channels"]),
                "open": rec.get("open", True),
                "from_lrd": bool(rec.get("lrd_sha")),
                "size_bytes": pq.stat().st_size if pq.exists() else 0,
            }
        )
    out.sort(key=lambda r: (r["started_at"] or r["imported_at"]), reverse=True)
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


def _query_window(
    source_id: str, cols: list[str], lo: float, hi: float
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """time_s plus the named channels for [lo, hi] (None bounds = everything), NULLs as NaN."""
    sel = ", ".join(f'"{c}"' for c in cols)
    con = duckdb.connect()
    try:
        arr = con.execute(
            f"SELECT {sel} FROM read_parquet(?) WHERE time_s >= ? AND time_s <= ? ORDER BY time_s",
            [str(_folder(source_id) / "data.parquet"), lo, hi],
        ).fetchnumpy()
    finally:
        con.close()
    t = np.asarray(arr["time_s"], dtype=float)
    # DuckDB returns NULLs as a masked array; np.asarray would turn them into 0.0
    out = {c: np.ma.filled(np.ma.asarray(arr[c], dtype=float), np.nan) for c in cols if c != "time_s"}
    return t, out


def _eval_derived(
    source_id: str, rec: dict, derived: dict[str, dict], wanted: list[str]
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Full-length arrays for the wanted derived channels, resolving chains of formulas."""
    base_names = {c["name"] for c in rec["channels"]} - set(derived)
    known = base_names | set(derived)
    need: set[str] = set()

    def collect(name: str, seen: tuple[str, ...] = ()) -> None:
        if name in seen:
            raise derived_mod.FormulaError(f"Circular formula involving '{name}'")
        if name in derived:
            for dep in derived_mod.referenced_names(derived[name]["expr"]) & known:
                collect(dep, (*seen, name))
        else:
            need.add(name)

    for w in wanted:
        collect(w)
    t, cols = _query_window(source_id, ["time_s", *sorted(need)], -np.inf, np.inf)
    memo: dict[str, np.ndarray] = dict(cols)

    def get(name: str) -> np.ndarray:
        if name not in memo:
            expr = derived[name]["expr"]
            env = {n: get(n) for n in derived_mod.referenced_names(expr) & known}
            memo[name] = derived_mod.evaluate(expr, env, t)
        return memo[name]

    return t, {w: get(w) for w in wanted}


def _window_with_derived(
    source_id: str, rec: dict, channels: list[str], derived: dict[str, dict], lo: float, hi: float
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    want_derived = [c for c in channels if c in derived]
    t, dvals = _eval_derived(source_id, rec, derived, want_derived)
    mask = (t >= lo) & (t <= hi)
    base = [c for c in channels if c not in derived]
    _, bvals = _query_window(source_id, ["time_s", *base], lo, hi)
    out = {c: dvals[c][mask] for c in want_derived}
    out.update(bvals)
    return t[mask], out


def read_window(
    source_id: str, channels: list[str], t0: float | None, t1: float | None
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Full-resolution samples for the window [t0, t1] (log time + offset), math channels included.

    Returned time is on the shared axis (offset applied).
    """
    rec = get_source(source_id)
    offset = float(rec.get("offset_s", 0.0))
    known = {c["name"] for c in rec["channels"]}
    bad = [c for c in channels if c not in known]
    if bad:
        raise ValueError(f"unknown channel(s): {', '.join(bad)}")
    lo = (t0 if t0 is not None else -np.inf) - offset
    hi = (t1 if t1 is not None else np.inf) - offset
    derived = {d["name"]: d for d in rec.get("derived", [])}
    if any(c in derived for c in channels):
        t, arr = _window_with_derived(source_id, rec, channels, derived, lo, hi)
    else:
        t, arr = _query_window(source_id, ["time_s", *channels], lo, hi)
    return t + offset, arr


MAX_RULES = 50


def _rule_flag(source_id: str, rec: dict, expr: str) -> tuple[np.ndarray, np.ndarray]:
    derived = {d["name"]: d for d in rec.get("derived", [])}
    derived["__rule__"] = {"name": "__rule__", "expr": expr}
    t, vals = _eval_derived(source_id, rec, derived, ["__rule__"])
    return t, vals["__rule__"]


def add_rule(source_id: str, name: str, expr: str, min_duration_s: float, merge_gap_s: float) -> dict:
    """Add an event rule: a true/false formula plus how long it must hold. Validates the formula."""
    name = name.strip()
    with _lock:
        rec = get_source(source_id)
        rules = rec.setdefault("rules", [])
        if not name or len(name) > 60:
            raise derived_mod.FormulaError("Rule name must be 1-60 characters")
        if any(r["name"] == name for r in rules):
            raise derived_mod.FormulaError(f"A rule called '{name}' already exists")
        if len(rules) >= MAX_RULES:
            raise derived_mod.FormulaError(f"At most {MAX_RULES} rules per log")
        _rule_flag(source_id, rec, expr)  # raises FormulaError if invalid
        rules.append(
            {
                "name": name,
                "expr": expr.strip(),
                "min_duration_s": max(float(min_duration_s), 0.0),
                "merge_gap_s": max(float(merge_gap_s), 0.0),
            }
        )
        (_folder(source_id) / "meta.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
        return rec


def remove_rule(source_id: str, name: str) -> dict:
    with _lock:
        rec = get_source(source_id)
        rules = rec.get("rules", [])
        if not any(r["name"] == name for r in rules):
            raise KeyError(name)
        rec["rules"] = [r for r in rules if r["name"] != name]
        (_folder(source_id) / "meta.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
        return rec


def list_events(source_id: str) -> list[dict]:
    """Every rule's events on the shared time axis, earliest first."""
    rec = get_source(source_id)
    offset = float(rec.get("offset_s", 0.0))
    out: list[dict] = []
    for rule in rec.get("rules", []):
        t, flag = _rule_flag(source_id, rec, rule["expr"])
        for e in events_mod.find_events(t, flag, rule["min_duration_s"], rule["merge_gap_s"]):
            out.append({"rule": rule["name"], **e, "t_start": e["t_start"] + offset, "t_end": e["t_end"] + offset})
    out.sort(key=lambda e: e["t_start"])
    return out


def add_derived(source_id: str, name: str, expr: str, unit: str = "") -> dict:
    """Add a math channel. Raises FormulaError if the formula is invalid."""
    name = name.strip()
    with _lock:
        rec = get_source(source_id)
        if not name or len(name) > 60 or "," in name:
            raise derived_mod.FormulaError("Name must be 1-60 characters and contain no comma")
        if name == "time_s" or any(c["name"] == name for c in rec["channels"]):
            raise derived_mod.FormulaError(f"A channel called '{name}' already exists")
        derived = {d["name"]: d for d in rec.get("derived", [])}
        entry = {"name": name, "expr": expr.strip(), "unit": unit.strip()}
        derived[name] = entry
        _, vals = _eval_derived(source_id, rec, derived, [name])
        y = vals[name]
        if not np.isfinite(y).any():
            raise derived_mod.FormulaError("Formula produced no valid values")
        rec.setdefault("derived", []).append(entry)
        rec["channels"].append(
            {
                "name": name,
                "unit": entry["unit"],
                "min": float(np.nanmin(y)),
                "max": float(np.nanmax(y)),
                "derived": True,
                "expr": entry["expr"],
            }
        )
        (_folder(source_id) / "meta.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
        return rec


def remove_derived(source_id: str, name: str) -> dict:
    with _lock:
        rec = get_source(source_id)
        derived = rec.get("derived", [])
        if not any(d["name"] == name for d in derived):
            raise KeyError(name)
        users = [
            d["name"]
            for d in derived
            if d["name"] != name and name in derived_mod.referenced_names(d["expr"])
        ]
        if users:
            raise derived_mod.FormulaError(f"'{name}' is used by {', '.join(users)}")
        rec["derived"] = [d for d in derived if d["name"] != name]
        rec["channels"] = [c for c in rec["channels"] if c["name"] != name]
        (_folder(source_id) / "meta.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
        return rec


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
    # one-sample margin is added in minmax_downsample, so over-fetch slightly
    pad = 2.0 / max(float(rec.get("sample_rate_hz") or 1.0), 1e-6)
    derived = {d["name"]: d for d in rec.get("derived", [])}
    if any(c in derived for c in channels):
        t, arr = _window_with_derived(source_id, rec, channels, derived, lo - pad, hi + pad)
    else:
        t, arr = _query_window(source_id, ["time_s", *channels], lo - pad, hi + pad)

    result: dict[str, dict] = {}
    full = True
    for c in channels:
        y = arr[c]
        tt, yy, is_full = minmax_downsample(t, y, lo, hi, max(px, 16))
        full = full and is_full
        result[c] = {"t": np.round(tt + offset, 6).tolist(), "v": yy.tolist()}
    return {"source_id": source_id, "offset_s": offset, "full_resolution": full, "channels": result}
