"""Flexible CSV log importer.

Real ECU/HCU exports vary: delimiter, header rows, a units row under the header,
time in seconds or milliseconds, text columns, duplicated or missing samples.
This importer sniffs those things, normalises everything to a DataFrame with a
``time_s`` column (starting at 0) plus numeric channels, and reports every
assumption it made in ``meta["warnings"]`` / ``meta["assumptions"]`` so the UI can
show them and the user can override with a mapping profile.

A mapping profile is a plain dict (stored as JSON) with optional keys:
    time_column: str        which column is time
    time_unit:   "s"|"ms"|"us"
    rename:      {old: new} channel renames
    units:       {channel: unit} channel units
    drop:        [channel, ...] channels to ignore
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

TIME_NAME_RE = re.compile(r"^(time|timestamp|t|elapsed|seconds|secs|sec)([\s_\-\(\[]|$)", re.I)

UNIT_SUFFIXES = {
    "_nm": "Nm",
    "_rpm": "rpm",
    "_v": "V",
    "_a": "A",
    "_c": "°C",
    "_pct": "%",
    "_kpa": "kPa",
    "_kw": "kW",
    "_kmh": "km/h",
    "_ms": "ms",
    "_s": "s",
    "_deg": "°",
}
BRACKET_UNIT_RE = re.compile(r"[\(\[]\s*([^\)\]]+?)\s*[\)\]]\s*$")


class ImportErrorDetail(ValueError):
    """Raised when a file cannot be turned into a usable log."""


@dataclass
class ParsedLog:
    df: pd.DataFrame  # columns: time_s, then numeric channels
    meta: dict = field(default_factory=dict)


def _decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeError:
            continue
    raise ImportErrorDetail("Could not decode file as text")


def _is_number(s: str) -> bool:
    s = s.strip()
    if not s:
        return False
    try:
        float(s.replace(",", ".")) if s.count(",") == 1 and s.count(".") == 0 else float(s)
        return True
    except ValueError:
        return False


def _sniff_delimiter(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        first = sample.splitlines()[0] if sample.splitlines() else ""
        return max(",;\t|", key=first.count) if any(first.count(d) for d in ",;\t|") else ","


def _clean_name(name: str) -> str:
    return re.sub(r"\s+", " ", str(name)).strip()


def _unit_from_name(name: str) -> str:
    m = BRACKET_UNIT_RE.search(name)
    if m:
        return m.group(1)
    low = name.lower()
    for suffix, unit in UNIT_SUFFIXES.items():
        if low.endswith(suffix):
            return unit
    return ""


def parse_csv(raw: bytes, profile: dict | None = None) -> ParsedLog:
    profile = profile or {}
    warnings: list[str] = []
    assumptions: list[str] = []

    text = _decode(raw)
    if not text.strip():
        raise ImportErrorDetail("File is empty")

    sample = text[:65536]
    delim = _sniff_delimiter(sample)
    assumptions.append(f"delimiter {delim!r}")

    head = pd.read_csv(io.StringIO(text), sep=delim, header=None, nrows=4, dtype=str, engine="python")
    row0 = [str(x) for x in head.iloc[0].fillna("")]
    has_header = not all(_is_number(c) for c in row0 if c.strip())
    units_row = False
    if has_header and len(head) >= 3:
        row1 = [str(x) for x in head.iloc[1].fillna("")]
        row2 = [str(x) for x in head.iloc[2].fillna("")]
        nonnum1 = sum(1 for c in row1 if c.strip() and not _is_number(c))
        num2 = sum(1 for c in row2 if _is_number(c))
        units_row = nonnum1 >= max(2, len(row1) // 2) and num2 >= max(2, len(row2) // 2)

    skip = [1] if units_row else None
    df = pd.read_csv(
        io.StringIO(text),
        sep=delim,
        header=0 if has_header else None,
        skiprows=skip,
        engine="c",
        skipinitialspace=True,
    )
    if not has_header:
        df.columns = [f"ch_{i}" for i in range(df.shape[1])]
        assumptions.append("no header row; channels named ch_0, ch_1, ...")
    df.columns = [_clean_name(c) for c in df.columns]

    units: dict[str, str] = {}
    if units_row:
        raw_units = [str(x).strip() for x in head.iloc[1].fillna("")]
        units = {c: u for c, u in zip(df.columns, raw_units)}
        assumptions.append("second row treated as units")

    # numeric coercion
    dropped_text: list[str] = []
    for c in list(df.columns):
        if not pd.api.types.is_numeric_dtype(df[c]):
            conv = pd.to_numeric(df[c], errors="coerce")
            if conv.notna().mean() >= 0.9:
                df[c] = conv
            else:
                dropped_text.append(c)
                df = df.drop(columns=c)
    if dropped_text:
        warnings.append(f"ignored non-numeric columns: {', '.join(dropped_text)}")

    all_nan = [c for c in df.columns if df[c].isna().all()]
    if all_nan:
        df = df.drop(columns=all_nan)
        warnings.append(f"ignored empty columns: {', '.join(all_nan)}")

    # time column
    tcol = profile.get("time_column")
    if tcol is None:
        for c in df.columns:
            if TIME_NAME_RE.match(c):
                tcol = c
                break
    if tcol is None and len(df.columns):
        first = df.columns[0]
        if df[first].is_monotonic_increasing:
            tcol = first
            warnings.append(f"no obvious time column; assumed first column '{first}'")
    if tcol is None or tcol not in df.columns:
        raise ImportErrorDetail(
            "Could not find a time column. Provide time_column in the mapping profile."
        )
    assumptions.append(f"time column '{tcol}'")

    t = df[tcol].to_numpy(dtype=float)
    if np.isnan(t).any():
        keep = ~np.isnan(t)
        warnings.append(f"dropped {int((~keep).sum())} rows with missing time")
        df, t = df[keep].reset_index(drop=True), t[keep]

    unit = profile.get("time_unit")
    if unit is None:
        low = tcol.lower()
        if re.search(r"(^|[^a-z])(ms|msec|millis)", low):
            unit = "ms"
        elif re.search(r"(^|[^a-z])(us|usec|micros)", low):
            unit = "us"
        elif re.search(r"(^|[^a-z])(s|sec|secs|seconds)([^a-z]|$)", low) or low in ("time", "t"):
            unit = "s"
        else:
            med = float(np.median(np.diff(t))) if t.size > 1 else 0.0
            unit = "ms" if med >= 1.0 else "s"
            warnings.append(
                f"time unit of '{tcol}' not stated; guessed {unit!r} from sample spacing"
            )
    scale = {"s": 1.0, "ms": 1e-3, "us": 1e-6}[unit]
    assumptions.append(f"time unit {unit}")

    if t.size < 2:
        raise ImportErrorDetail("Log has fewer than 2 samples")

    if not np.all(np.diff(t) >= 0):
        order = np.argsort(t, kind="stable")
        df, t = df.iloc[order].reset_index(drop=True), t[order]
        warnings.append("time was not monotonic; rows re-sorted")
    dup = np.diff(t) == 0
    if dup.any():
        keep = np.concatenate([[True], ~dup])
        warnings.append(f"removed {int(dup.sum())} duplicate-timestamp rows")
        df, t = df[keep].reset_index(drop=True), t[keep]

    time_origin_raw = float(t[0])
    time_s = (t - t[0]) * scale

    drop = set(profile.get("drop", []))
    channels = [c for c in df.columns if c != tcol and c not in drop]
    out = pd.DataFrame({"time_s": time_s})
    rename = profile.get("rename", {})
    for c in channels:
        out[rename.get(c, c)] = df[c].to_numpy(dtype=float)

    final_units = {}
    for c in channels:
        name = rename.get(c, c)
        final_units[name] = (
            profile.get("units", {}).get(name) or units.get(c) or _unit_from_name(name)
        )

    dts = np.diff(time_s)
    med_dt = float(np.median(dts))
    gaps = int((dts > 5 * med_dt).sum())
    if gaps:
        warnings.append(f"{gaps} gap(s) longer than 5x the median sample spacing (kept as gaps)")

    meta = {
        "rows": int(len(out)),
        "channels": [
            {
                "name": c,
                "unit": final_units.get(c, ""),
                "min": float(np.nanmin(out[c])),
                "max": float(np.nanmax(out[c])),
            }
            for c in out.columns
            if c != "time_s"
        ],
        "duration_s": float(time_s[-1]),
        "sample_rate_hz": round(1.0 / med_dt, 3) if med_dt > 0 else None,
        "gaps": gaps,
        "time_origin_raw": time_origin_raw,
        "time_column": tcol,
        "time_unit": unit,
        "assumptions": assumptions,
        "warnings": warnings,
    }
    return ParsedLog(out, meta)
