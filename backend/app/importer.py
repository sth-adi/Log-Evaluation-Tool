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
import hashlib
import io
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

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

# Life Racing log names: "2025-11-19 11-53-32 plus 0h00m00s F88#12357 Dyno run final.LRD"
SESSION_NAME_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})[ T](\d{2})[-:](\d{2})[-:](\d{2})(?: plus (\d+)h(\d+)m(\d+)s)?")
MAX_STATES = 32  # a text column with at most this many distinct values is a state channel


def find_start_time(*texts: str) -> str | None:
    """ISO wall-clock start of the session if a log name or preamble line carries one."""
    for t in texts:
        m = SESSION_NAME_RE.search(t or "")
        if m:
            y, mo, d, h, mi, sec = (int(x) for x in m.groups()[:6])
            oh, om, os_ = (int(x or 0) for x in m.groups()[6:])
            try:
                dt = datetime(y, mo, d, h, mi, sec) + timedelta(hours=oh, minutes=om, seconds=os_)
            except ValueError:
                continue
            return dt.isoformat()
    return None


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
    if set(s) == {"#"}:  # "####" is the missing-value placeholder
        return True
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


def _split_preamble(text: str) -> tuple[str, str, int]:
    """Find the real table inside a file with free-text lines above it.

    Some exports (e.g. Life Racing) start with a source path, a time range and a
    blank line before the header. For each candidate delimiter, take the most
    common field count (>= 2) over the first lines; the table starts at the first
    line with that count. Returns (table_text, delimiter, lines_skipped).
    """
    lines = text.splitlines()
    window = lines[:300]
    best: tuple[int, str, int] | None = None  # (agreeing lines, delim, fields)
    for d in ",;\t|":
        counts = [len(next(csv.reader([ln], delimiter=d), [])) for ln in window if ln.strip()]
        counts = [c for c in counts if c >= 2]
        if not counts:
            continue
        n = max(set(counts), key=counts.count)
        agree = counts.count(n)
        if best is None or agree > best[0]:
            best = (agree, d, n)
    if best is None:
        return text, _sniff_delimiter(text[:65536]), 0
    _, d, n = best
    for i, ln in enumerate(lines):
        if ln.strip() and len(next(csv.reader([ln], delimiter=d), [])) == n:
            return "\n".join(lines[i:]), d, i
    return text, d, 0


def _clean_name(name: str) -> str:
    return re.sub(r"\s+", " ", str(name)).strip()


# Exports from the F88R tools carry no units, so fall back to the usual meaning of the channel
# name. Checked in order against the lower-cased name; the first match wins. These are guesses:
# whatever is used gets listed in the importer's assumptions so it can be overridden.
NAME_UNIT_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"rpm|enginespeed|engspeed"), "rpm"),
    (re.compile(r"(^|[^a-z])(ect|act|iat|egt|clt|oilt|coolant|airtemp)|temp"), "°C"),
    (re.compile(r"speed|kph|^vss"), "km/h"),
    (re.compile(r"^(tps|ap|app|pedal|throttle|duty|ethanol|fuelpump)|pct|percent"), "%"),
    (re.compile(r"batt|volt|^vbat|^vref"), "V"),
    (re.compile(r"^(map|baro)|kpa"), "kPa"),
    (re.compile(r"inj.*(pw|pulse)|pulsewidth"), "ms"),
    (re.compile(r"ign|advance|timing"), "°"),
]


def _unit_from_name(name: str) -> str:
    m = BRACKET_UNIT_RE.search(name)
    if m:
        return m.group(1)
    low = name.lower()
    for suffix, unit in UNIT_SUFFIXES.items():
        if low.endswith(suffix):
            return unit
    return ""


def _guess_unit(name: str) -> str:
    unit = _unit_from_name(name)
    if unit:
        return unit
    low = name.lower()
    for rx, u in NAME_UNIT_RULES:
        if rx.search(low):
            return u
    return ""


def content_sha(raw: bytes) -> str:
    """Fingerprint of the table in a CSV (header and rows), ignoring the text lines above it.

    The same log exported twice, or from another folder, has the same fingerprint even though the
    path written on its first line differs.
    """
    text, _delim, _skipped = _split_preamble(_decode(raw))
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()


def parse_csv(raw: bytes, profile: dict | None = None, filename: str = "") -> ParsedLog:
    profile = profile or {}
    warnings: list[str] = []
    assumptions: list[str] = []

    text = _decode(raw)
    if not text.strip():
        raise ImportErrorDetail("File is empty")

    preamble = " | ".join(text.splitlines()[:5])
    text, delim, skipped = _split_preamble(text)
    assumptions.append(f"delimiter {delim!r}")
    if skipped:
        assumptions.append(f"skipped {skipped} line(s) of text above the table")

    try:
        head = pd.read_csv(
            io.StringIO(text), sep=delim, header=None, nrows=4, dtype=str, engine="python"
        )
    except (pd.errors.ParserError, pd.errors.EmptyDataError) as e:
        raise ImportErrorDetail(f"Could not read the file as a table: {e}") from e
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
        na_values=["####"],
        on_bad_lines="skip",
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

    # numeric coercion; short text columns (OFF/ON, run modes) become state channels
    dropped_text: list[str] = []
    states: dict[str, dict[str, str]] = {}
    for c in list(df.columns):
        if not pd.api.types.is_numeric_dtype(df[c]):
            conv = pd.to_numeric(df[c], errors="coerce")
            if conv.notna().mean() >= 0.9:
                df[c] = conv
                continue
            col = df[c].astype("string").str.strip()
            labels = sorted(col.dropna().unique())
            if 0 < len(labels) <= MAX_STATES and len(labels) <= 0.5 * col.notna().sum():
                df[c] = col.map({lab: float(i) for i, lab in enumerate(labels)}).astype(float)
                states[c] = {str(i): lab for i, lab in enumerate(labels)}
            else:
                dropped_text.append(c)
                df = df.drop(columns=c)
    if dropped_text:
        warnings.append(f"ignored non-numeric columns: {', '.join(dropped_text)}")
    if states:
        assumptions.append(
            f"{len(states)} text column(s) read as state channels (value = index of the label)"
        )

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
    guessed: list[str] = []
    for c in channels:
        name = rename.get(c, c)
        given = profile.get("units", {}).get(name) or units.get(c) or _unit_from_name(name)
        if given:
            final_units[name] = given
        else:
            final_units[name] = _guess_unit(name)
            if final_units[name]:
                guessed.append(f"{name} = {final_units[name]}")
    if guessed:
        assumptions.append(
            "units guessed from channel names (the file has none): " + ", ".join(guessed)
        )

    dts = np.diff(time_s)
    med_dt = float(np.median(dts))
    gaps = int((dts > 5 * med_dt).sum())
    if gaps:
        warnings.append(f"{gaps} gap(s) longer than 5x the median sample spacing (kept as gaps)")

    inv_rename = {v: k for k, v in rename.items()}
    meta = {
        "content_sha": content_sha(raw),
        "started_at": find_start_time(preamble, filename),
        "rows": int(len(out)),
        "channels": [
            {
                "name": c,
                "unit": final_units.get(c, ""),
                "min": float(np.nanmin(out[c])),
                "max": float(np.nanmax(out[c])),
                **({"states": states[inv_rename.get(c, c)]} if inv_rename.get(c, c) in states else {}),
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
