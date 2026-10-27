"""On-disk storage: one folder per imported source (Parquet data + JSON metadata).

Everything lives under LET_DATA_DIR (default: <repo>/data). Nothing here ever
talks to a vehicle; logs are only read from files the user imports.
"""

from __future__ import annotations

import json
import logging
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
import pyarrow

log = logging.getLogger(__name__)

from . import derived as derived_mod
from . import events as events_mod
from .downsample import minmax_downsample
from .rates import native_rate_hz

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


_reg_lock = threading.Lock()


def _canonical_states(df: pd.DataFrame, channels: list[dict]) -> None:
    """Number the labels of every text channel the same way in all logs.

    The importer numbers a log's labels by sorting the ones that log contains, so NEUTRAL could be
    2 in one log and 1 in another. A library-wide list per channel (``state_labels.json``, only ever
    appended to) gives each label one number for good. Rewrites ``df`` and the channel entries."""
    todo = [c for c in channels if c.get("label_index") and c["name"] in df.columns]
    if not todo:
        return
    with _reg_lock:
        path = data_dir() / "state_labels.json"
        registry: dict[str, list[str]] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        before = json.dumps(registry, sort_keys=True)
        for ch in todo:
            labels = registry.setdefault(ch["name"], [])
            for lab in ch["states"].values():
                if lab not in labels:
                    labels.append(lab)
            renumber = {float(i): float(labels.index(lab)) for i, lab in ch["states"].items()}
            df[ch["name"]] = df[ch["name"]].map(renumber)
            ch["states"] = {str(i): lab for i, lab in enumerate(labels)}
            ch["min"] = float(np.nanmin(df[ch["name"]]))
            ch["max"] = float(np.nanmax(df[ch["name"]]))
        if json.dumps(registry, sort_keys=True) != before:
            path.write_text(json.dumps(registry, indent=1), encoding="utf-8")


_codes_done: set[str] = set()
_CAN_SUFFIXES = (".asc", ".blf", ".trc")


def _backfill_state_codes() -> None:
    """Renumber the text channels of logs imported before the numbering was shared between logs."""
    d = str(data_dir())
    if d in _codes_done:
        return
    _codes_done.add(d)
    for rec in list_sources(include_closed=True):
        if rec.get("states_stable"):
            continue
        # CAN signals carry the DBC's own numbers, which are not ours to change
        index_coded = not rec.get("filename", "").lower().endswith(_CAN_SUFFIXES)
        chans = [c for c in rec["channels"] if c.get("states") and not c.get("derived")]
        if index_coded and chans:
            for c in chans:
                c["label_index"] = True
            path = _folder(rec["id"]) / "data.parquet"
            try:
                df = pd.read_parquet(path)
                _canonical_states(df, rec["channels"])
                df.to_parquet(path.with_suffix(".tmp"), index=False, row_group_size=65536)
                path.with_suffix(".tmp").replace(path)
            except (OSError, ValueError, pyarrow.ArrowException) as e:  # the log stays usable, numbered as it was
                log.warning("could not renumber the state channels of %s: %s", rec["id"], e)
                continue
        update_source(rec["id"], channels=rec["channels"], states_stable=True)


def create_source(
    df: pd.DataFrame, meta: dict, label: str, kind: str, filename: str, extra: dict | None = None
) -> dict:
    source_id = uuid.uuid4().hex[:10]
    folder = data_dir() / "sources" / source_id
    folder.mkdir(parents=True)
    _canonical_states(df, meta["channels"])
    df.to_parquet(folder / "data.parquet", index=False, row_group_size=65536)
    record = {
        "states_stable": True,
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


_rates_done: set[str] = set()


def _backfill_rates() -> None:
    """Estimate each channel's real update rate for logs imported before that was recorded."""
    d = str(data_dir())
    if d in _rates_done:
        return
    _rates_done.add(d)
    for rec in list_sources(include_closed=True):
        if rec.get("rates_checked"):
            continue
        base = [c["name"] for c in rec["channels"] if not c.get("derived")]
        try:
            df = pd.read_parquet(_folder(rec["id"]) / "data.parquet", columns=["time_s", *base])
        except (OSError, ValueError, pyarrow.ArrowException) as e:  # the log stays usable without rates
            log.warning("could not estimate update rates for %s: %s", rec["id"], e)
            continue
        dt = float(np.median(np.diff(df["time_s"].to_numpy()))) if len(df) > 1 else 0.0
        raster = 1.0 / dt if dt > 0 else 0.0
        channels = []
        for c in rec["channels"]:
            c = {k: v for k, v in c.items() if k != "native_hz"}
            r = None if c.get("derived") else native_rate_hz(df[c["name"]].to_numpy(dtype=float), raster)
            channels.append({**c, **({"native_hz": r} if r else {})})
        update_source(rec["id"], channels=channels, rates_checked=True)


def list_sources(include_closed: bool = False) -> list[dict]:
    """Logs in the current view (open ones), or every stored log with include_closed."""
    _backfill_state_codes()
    _backfill_rates()
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
            except (OSError, ValueError) as e:  # without a fingerprint this log cannot be recognised as a duplicate
                log.warning("could not fingerprint %s: %s", kept, e)


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


def arrange_sources(mode: str, gap_s: float, max_gap_s: float = 1200.0) -> list[dict]:
    """Set offsets so logs sit in session-start order.

    "sequential" lays them end to end (what LifeView's concatenated view does); "real" keeps the
    true wall-clock spacing between sessions, except that a gap longer than ``max_gap_s`` (default
    20 minutes) is shortened to that, so tests on different days still fit on one screen. Short gaps
    and overlaps (an ECU and an HCU log recorded at once) stay exactly as they were. Logs with no
    known start time go after the others, in import order.
    """
    with _lock:
        recs = list_sources()
        dated = sorted((r for r in recs if r.get("started_at")), key=lambda r: r["started_at"])
        undated = [r for r in recs if not r.get("started_at")]
        t0 = datetime.fromisoformat(dated[0]["started_at"]) if dated else None
        cursor = 0.0
        shortened = 0.0  # seconds removed from long gaps so far
        prev_end = None  # real time at which the previous log ended
        for r in dated + undated:
            if mode == "real" and r.get("started_at"):
                real = (datetime.fromisoformat(r["started_at"]) - t0).total_seconds()
                if prev_end is not None and real - prev_end > max_gap_s:
                    shortened += (real - prev_end) - max_gap_s
                off = real - shortened
                prev_end = max(prev_end or 0.0, real + float(r["duration_s"]))
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
