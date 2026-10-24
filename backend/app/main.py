"""FastAPI application: import logs, list sources, serve downsampled signals.

Run (from the repo root):
    python -m uvicorn backend.app.main:app --port 8000
The built frontend (frontend/dist) is served from the same port when present.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import io
import re

import numpy as np
import pandas as pd
from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import analysis, laps, lifeview, live, pulls, report, store, workspaces
from .downsample import minmax_downsample
from .derived import FormulaError
from .importer import ImportErrorDetail, parse_csv

MAX_UPLOAD_BYTES = 512 * 1024 * 1024
KINDS = {"ecu", "hcu", "other"}

app = FastAPI(title="Log Evaluation Tool", version="0.1.0")
app.include_router(live.router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "data_dir": str(store.data_dir())}


@app.post("/api/sources")
async def import_source(
    file: UploadFile = File(...),
    label: str = Form(""),
    kind: str = Form("other"),
    profile: str = Form(""),
) -> dict:
    if kind not in KINDS:
        raise HTTPException(422, f"kind must be one of {sorted(KINDS)}")
    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "file too large")
    try:
        prof = json.loads(profile) if profile.strip() else None
    except json.JSONDecodeError as e:
        raise HTTPException(422, f"profile is not valid JSON: {e}") from e
    try:
        parsed = parse_csv(raw, prof, file.filename or "")
    except ImportErrorDetail as e:
        raise HTTPException(422, str(e)) from e
    name = file.filename or "upload.csv"
    if not prof:  # same data already stored: open that one instead of making a copy
        existing = store.find_existing(content_sha=parsed.meta["content_sha"])
        if existing:
            if not existing.get("open", True):
                existing = store.update_source(existing["id"], open=True)
            return {**existing, "reused": True}
    return store.create_source(parsed.df, parsed.meta, label or Path(name).stem, kind, name)


@app.get("/api/convert/status")
def convert_status() -> dict:
    """Can .LRD logs be converted on this machine, and is LifeView already open?"""
    st = lifeview.status()
    st["lifeview_open"] = lifeview.lifeview_running() if st["available"] else False
    return st


@app.post("/api/convert", status_code=202)
async def convert(files: list[UploadFile] = File(...)) -> dict:
    """Convert .LRD logs with LifeView, then import the CSVs. Returns a job to poll."""
    st = lifeview.status()
    if not st["available"]:
        raise HTTPException(422, st["reason"])
    if lifeview.lifeview_running():
        raise HTTPException(409, "LifeView is already open. Close it, then try again.")
    batch: list[tuple[str, bytes]] = []
    for f in files:
        name = Path(f.filename or "").name
        if not name.lower().endswith(".lrd"):
            raise HTTPException(422, f"{name or 'A file'} is not a .LRD log.")
        data = await f.read()
        if not data or len(data) > lifeview.MAX_LRD_BYTES:
            raise HTTPException(422, f"{name} is empty or too large.")
        batch.append((name, data))
    if not batch:
        raise HTTPException(422, "Choose at least one .LRD log.")
    try:
        return lifeview.start(batch).public()
    except lifeview.Busy as e:
        raise HTTPException(409, str(e)) from None


@app.get("/api/convert/{job_id}")
def convert_job(job_id: str) -> dict:
    try:
        return lifeview.get(job_id).public()
    except KeyError:
        raise HTTPException(404, "unknown conversion") from None


@app.post("/api/convert/{job_id}/cancel")
def convert_cancel(job_id: str) -> dict:
    try:
        return lifeview.cancel(job_id).public()
    except KeyError:
        raise HTTPException(404, "unknown conversion") from None


@app.get("/api/library")
def library() -> list[dict]:
    """All processed logs, open or not: the place to pick logs from without converting again."""
    return store.library()


@app.post("/api/library/folder/open")
def library_open_folder() -> dict:
    """Show the folder holding the CSV copies in Explorer."""
    folder = store.data_dir() / "exports"
    folder.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(folder)  # noqa: S606 - a folder we own
    return {"path": str(folder)}


@app.post("/api/library/{source_id}/open")
def library_open(source_id: str) -> dict:
    try:
        return store.update_source(source_id, open=True)
    except KeyError:
        raise HTTPException(404, "unknown log") from None


@app.post("/api/library/{source_id}/close")
def library_close(source_id: str) -> dict:
    try:
        return store.update_source(source_id, open=False)
    except KeyError:
        raise HTTPException(404, "unknown log") from None


@app.get("/api/sources")
def sources() -> list[dict]:
    return store.list_sources()


@app.get("/api/sources/{source_id}")
def source(source_id: str) -> dict:
    try:
        return store.get_source(source_id)
    except KeyError:
        raise HTTPException(404, "unknown source") from None


class SourcePatch(BaseModel):
    label: str | None = None
    kind: str | None = None
    offset_s: float | None = None


@app.patch("/api/sources/{source_id}")
def patch_source(source_id: str, body: SourcePatch) -> dict:
    if body.kind is not None and body.kind not in KINDS:
        raise HTTPException(422, f"kind must be one of {sorted(KINDS)}")
    try:
        return store.update_source(source_id, **body.model_dump())
    except KeyError:
        raise HTTPException(404, "unknown source") from None


class ArrangeBody(BaseModel):
    mode: str = "sequential"  # "sequential" = back to back, "real" = true wall-clock spacing
    gap_s: float = 0.0
    max_gap_s: float = 1200.0  # "real" mode: longest true gap kept, in seconds


@app.post("/api/arrange")
def arrange(body: ArrangeBody) -> list[dict]:
    """Order logs by session start time (as LifeView does) and set their time offsets."""
    if body.mode not in ("sequential", "real"):
        raise HTTPException(422, "mode must be 'sequential' or 'real'")
    return store.arrange_sources(body.mode, max(body.gap_s, 0.0), max(body.max_gap_s, 0.0))


@app.delete("/api/sources/{source_id}", status_code=204)
def delete_source(source_id: str) -> None:
    try:
        store.delete_source(source_id)
    except KeyError:
        raise HTTPException(404, "unknown source") from None


class DerivedBody(BaseModel):
    name: str
    expr: str
    unit: str = ""


@app.post("/api/sources/{source_id}/derived")
def add_derived(source_id: str, body: DerivedBody) -> dict:
    try:
        return store.add_derived(source_id, body.name, body.expr, body.unit)
    except KeyError:
        raise HTTPException(404, "unknown source") from None
    except FormulaError as e:
        raise HTTPException(422, str(e)) from e


@app.delete("/api/sources/{source_id}/derived/{name}")
def remove_derived(source_id: str, name: str) -> dict:
    try:
        return store.remove_derived(source_id, name)
    except KeyError:
        raise HTTPException(404, "unknown source or math channel") from None
    except FormulaError as e:
        raise HTTPException(422, str(e)) from e


@app.get("/api/sources/{source_id}/signals")
def signals(
    source_id: str,
    channels: str = Query(..., description="comma-separated channel names"),
    t0: float | None = None,
    t1: float | None = None,
    px: int = Query(1200, ge=16, le=8000, description="target plot width in pixels"),
) -> dict:
    names = [c for c in channels.split(",") if c]
    if not names:
        raise HTTPException(422, "no channels requested")
    try:
        return store.read_signals(source_id, names, t0, t1, px)
    except KeyError:
        raise HTTPException(404, "unknown source") from None
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


class RuleBody(BaseModel):
    name: str
    expr: str
    min_duration_s: float = 0.0
    merge_gap_s: float = 0.0


@app.post("/api/sources/{source_id}/rules")
def add_rule(source_id: str, body: RuleBody) -> dict:
    try:
        return store.add_rule(source_id, body.name, body.expr, body.min_duration_s, body.merge_gap_s)
    except KeyError:
        raise HTTPException(404, "unknown source") from None
    except FormulaError as e:
        raise HTTPException(422, str(e)) from e


@app.delete("/api/sources/{source_id}/rules/{name}")
def remove_rule(source_id: str, name: str) -> dict:
    try:
        return store.remove_rule(source_id, name)
    except KeyError:
        raise HTTPException(404, "unknown source or rule") from None


@app.get("/api/sources/{source_id}/events")
def events(source_id: str) -> list[dict]:
    try:
        return store.list_events(source_id)
    except KeyError:
        raise HTTPException(404, "unknown source") from None
    except FormulaError as e:
        raise HTTPException(422, str(e)) from e


@app.get("/api/sources/{source_id}/export")
def export_source(
    source_id: str,
    format: str = Query("csv", pattern="^(csv|parquet)$"),
    channels: str = Query("", description="comma-separated channel names; empty means all"),
    t0: float | None = None,
    t1: float | None = None,
) -> Response:
    """The log's data (calculated channels included) as a CSV or Parquet file, optionally cut down."""
    try:
        rec = store.get_source(source_id)
    except KeyError:
        raise HTTPException(404, "unknown source") from None
    names = [c for c in channels.split(",") if c] or [c["name"] for c in rec["channels"]]
    t, arr = _window(source_id, names, t0, t1)
    # log time starts at zero in the file, whatever offset the log has on the shared timeline
    df = pd.DataFrame({"time_s": t - float(rec.get("offset_s", 0.0)), **{n: arr[n] for n in names}})
    buf = io.BytesIO()
    if format == "parquet":
        df.to_parquet(buf, index=False)
        media = "application/octet-stream"
    else:
        df.to_csv(buf, index=False, encoding="utf-8")
        media = "text/csv; charset=utf-8"
    stem = re.sub(r"[^\w.\- ]+", "_", rec["label"]).strip()[:80] or "log"
    return Response(
        buf.getvalue(),
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{stem}.{format}"'},
    )


@app.get("/api/sources/{source_id}/report", response_class=HTMLResponse)
def report_page(
    source_id: str, channels: str = Query(...), t0: float | None = None, t1: float | None = None
) -> HTMLResponse:
    """A single self-contained HTML report (plots, statistics, events) for the chosen channels."""
    names = [c for c in channels.split(",") if c][:12]
    if not names:
        raise HTTPException(422, "Choose at least one channel")
    t, arr = _window(source_id, names, t0, t1)
    rec = store.get_source(source_id)
    x0, x1 = (t0 if t0 is not None else float(t[0])), (t1 if t1 is not None else float(t[-1]))
    if x1 <= x0:
        raise HTTPException(422, "Empty time window")
    try:
        events = [e for e in store.list_events(source_id) if e["t_end"] >= x0 and e["t_start"] <= x1]
    except FormulaError:
        events = []
    plots = []
    for c in names:
        tt, yy, _ = minmax_downsample(t, arr[c], x0, x1, 900)
        unit = next((k["unit"] for k in rec["channels"] if k["name"] == c), "")
        plots.append([(c, unit, tt, yy)])
    stats = {c: analysis.stats(arr[c], t) for c in names}
    return HTMLResponse(report.render(rec, stats, plots, events, x0, x1))


def _window(source_id: str, channels: list[str], t0, t1):
    try:
        t, arr = store.read_window(source_id, channels, t0, t1)
    except KeyError:
        raise HTTPException(404, "unknown source") from None
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    if t.size == 0:
        raise HTTPException(422, "No samples in that time window")
    return t, arr


@app.get("/api/sources/{source_id}/stats")
def channel_stats(
    source_id: str, channels: str = Query(...), t0: float | None = None, t1: float | None = None
) -> dict:
    names = [c for c in channels.split(",") if c]
    t, arr = _window(source_id, names, t0, t1)
    return {
        "t0": float(t[0]),
        "t1": float(t[-1]),
        "channels": {c: analysis.stats(arr[c], t) for c in names},
    }


@app.get("/api/sources/{source_id}/histogram")
def channel_histogram(
    source_id: str,
    channel: str,
    bins: int = Query(40, ge=2, le=400),
    t0: float | None = None,
    t1: float | None = None,
) -> dict:
    _, arr = _window(source_id, [channel], t0, t1)
    return analysis.histogram(arr[channel], bins)


@app.get("/api/sources/{source_id}/spectrum")
def channel_spectrum(
    source_id: str, channel: str, t0: float | None = None, t1: float | None = None
) -> dict:
    t, arr = _window(source_id, [channel], t0, t1)
    try:
        return analysis.spectrum(t, arr[channel])
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@app.get("/api/sources/{source_id}/scatter")
def channel_scatter(
    source_id: str, x: str, y: str, t0: float | None = None, t1: float | None = None
) -> dict:
    t, arr = _window(source_id, [x] if x == y else [x, y], t0, t1)
    return analysis.scatter(t, arr[x], arr[y])


class ViewBody(BaseModel):
    name: str
    payload: dict


@app.get("/api/workspaces")
def list_views() -> list[dict]:
    return workspaces.list_all()


@app.put("/api/workspaces")
def save_view(body: ViewBody) -> dict:
    try:
        return workspaces.save(body.name, body.payload)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@app.delete("/api/workspaces/{view_id}", status_code=204)
def delete_view(view_id: str) -> None:
    try:
        workspaces.delete(view_id)
    except KeyError:
        raise HTTPException(404, "unknown view") from None


class LapQuery:
    """How to find the laps: the same few query parameters on every lap endpoint."""

    def __init__(
        self,
        method: str = "auto",
        channel: str | None = None,
        threshold: float = 0.5,
        length_m: float | None = None,
        times: str = "",
        min_lap_s: float = Query(5.0, ge=0.5),
        speed: str | None = None,
    ):
        self.method, self.channel, self.threshold = method, channel, threshold
        self.length_m, self.min_lap_s, self.speed = length_m, min_lap_s, speed
        try:
            self.times = [float(x) for x in times.split(",") if x.strip()]
        except ValueError:
            raise HTTPException(422, "Lap times must be numbers separated by commas") from None


def _lap_context(source_id: str, q: LapQuery, extra: list[str] | None = None, need_laps: bool = True) -> dict:
    """Load the columns lap work needs and find the laps (or, if need_laps is False, carry on without them)."""
    try:
        rec = store.get_source(source_id)
    except KeyError:
        raise HTTPException(404, "unknown source") from None
    info = {c["name"]: c for c in rec["channels"]}
    names = list(info)
    for c in [q.channel, q.speed, *(extra or [])]:
        if c and c not in info:
            raise HTTPException(422, f"unknown channel {c}")
    good = {n: info[n]["min"] >= 0 and info[n]["max"] > 1 for n in names}
    speed = q.speed or laps.pick_speed(names, good)
    if speed is None:  # fall back to the fastest-looking wheel channel
        speed = next((n for n in names if n.endswith("Speed") and good.get(n)), None)
    pos = laps.guess_position(names)
    want = {
        *(n for n, _ in laps.LAP_AUTO if n in info),
        *(c for c in [q.channel, speed, "gpsCourse", "latG", *(extra or [])] if c and c in info),
        *(pos or ()),
    }
    t, cols = _window(source_id, sorted(want), None, None)
    dist = laps.cumulative_distance(t, laps.to_mps(cols[speed], info[speed]["unit"])) if speed else None
    try:
        bounds, used = laps.lap_boundaries(
            t, cols, dist, q.method, q.channel, q.threshold, q.length_m, q.times, q.min_lap_s
        )
    except ValueError as e:
        if need_laps:
            raise HTTPException(422, str(e)) from e
        bounds, used = [], ""
    kmh = laps.to_mps(cols[speed], info[speed]["unit"]) * 3.6 if speed else None
    table = laps.lap_table(t, dist, kmh, bounds)
    return {"rec": rec, "info": info, "t": t, "cols": cols, "dist": dist, "speed": speed, "pos": pos,
            "bounds": bounds, "used": used, "table": table}


@app.get("/api/sources/{source_id}/laps")
def source_laps(source_id: str, q: LapQuery = Depends()) -> dict:
    c = _lap_context(source_id, q)
    return {
        "found_by": c["used"],
        "speed_channel": c["speed"],
        "has_position": c["pos"] is not None,
        "boundaries": c["bounds"],
        **c["table"],
    }


@app.get("/api/sources/{source_id}/lapview")
def lap_view(
    source_id: str,
    channels: str = Query(..., description="comma-separated channel names"),
    selected: str = "",
    ref: int | None = None,
    axis: str = Query("distance", pattern="^(distance|time)$"),
    points: int = Query(600, ge=50, le=3000),
    q: LapQuery = Depends(),
) -> dict:
    names = [x for x in channels.split(",") if x][:6]
    if not names:
        raise HTTPException(422, "Choose at least one channel")
    c = _lap_context(source_id, q, names)
    table = c["table"]
    if not table["laps"]:
        raise HTTPException(422, "No complete laps found")
    chosen = {int(x) for x in selected.split(",") if x.strip().isdigit()}
    use = [l for l in table["laps"] if (l["n"] in chosen if chosen else l["valid"])] or table["laps"]
    ref_n = ref if ref in {l["n"] for l in use} else (table["best"] if table["best"] in {l["n"] for l in use} else use[0]["n"])
    try:
        out = laps.overlay(c["t"], c["dist"], {n: c["cols"][n] for n in names}, use, ref_n, axis, points)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    out["best"] = table["best"]
    out["units"] = {n: c["info"][n]["unit"] for n in names}
    return out


def _collect_runs(ids: list[str], names: list[str], q: LapQuery, chosen: set[str]) -> tuple[list[dict], dict, list[dict]]:
    """Find laps in each log and gather what the lap overlays and tables need. Logs without laps are skipped."""
    runs, tables, skipped = [], {}, []
    for sid in ids:
        try:
            have = [n for n in names if n in {c["name"] for c in store.get_source(sid)["channels"]}]
            c = _lap_context(sid, q, have)
        except (HTTPException, KeyError) as e:
            skipped.append({"id": sid, "reason": e.detail if isinstance(e, HTTPException) else "unknown log"})
            continue
        table = c["table"]
        use = [l for l in table["laps"] if (f"{sid}:{l['n']}" in chosen if chosen else l["valid"])]
        if not use:
            continue
        tables[sid] = {"label": c["rec"]["label"], "started_at": c["rec"].get("started_at"), "best": table["best"],
                       "units": {n: c["info"][n]["unit"] for n in have}}
        runs.append({"key": sid, "t": c["t"], "dist": c["dist"], "cols": {n: c["cols"][n] for n in have}, "laps": use})
    if not runs:
        raise HTTPException(422, "No complete laps found in the chosen logs")
    return runs, tables, skipped


@app.get("/api/lapstats")
def lap_stats(
    sources: str = Query(..., description="comma-separated log ids"),
    channels: str = Query("", description="comma-separated channel names for per-lap min/max/mean"),
    selected: str = Query("", description="lap keys like id:3, comma-separated; default is every valid lap"),
    sectors: int = Query(3, ge=2, le=12),
    q: LapQuery = Depends(),
) -> dict:
    """Per-lap channel metrics, sector times and the ideal lap, across one or more logs."""
    names = [x for x in channels.split(",") if x][:8]
    ids = [x for x in sources.split(",") if x][:12]
    if not ids:
        raise HTTPException(422, "Choose at least one log")
    runs, tables, skipped = _collect_runs(ids, names, q, {x for x in selected.split(",") if x})
    out = laps.stats_runs(runs, sectors)
    out["logs"] = tables
    out["skipped"] = skipped
    out["units"] = {n: u for t in tables.values() for n, u in t["units"].items()}
    return out


@app.get("/api/pulls")
def engine_pulls(
    sources: str = Query(..., description="comma-separated log ids"),
    channels: str = Query("", description="comma-separated channels to plot against RPM"),
    selected: str = Query("", description="pull keys like id:2, comma-separated; default is every pull"),
    slope: float = Query(150.0, gt=0, description="RPM per second a sweep must climb at"),
    min_span: float = Query(3000.0, gt=0, description="RPM a sweep must cover"),
    bin: float = Query(100.0, ge=10, le=1000, description="RPM bin width"),
    mass_kg: float | None = Query(None, gt=0, description="effective mass for absolute power"),
    speed: str | None = None,
) -> dict:
    """Find the pulls in each log and compare them against RPM, with a power and torque estimate."""
    names = [x for x in channels.split(",") if x][:8]
    ids = [x for x in sources.split(",") if x][:12]
    if not ids:
        raise HTTPException(422, "Choose at least one log")
    chosen = {x for x in selected.split(",") if x}
    runs, logs, skipped = [], {}, []
    for sid in ids:
        try:
            rec = store.get_source(sid)
        except KeyError:
            skipped.append({"id": sid, "reason": "unknown log"})
            continue
        info = {c["name"]: c for c in rec["channels"]}
        rpm_name = next((n for n in info if n.lower() == "rpm"), None)
        if not rpm_name:
            skipped.append({"id": sid, "reason": "no rpm channel"})
            continue
        good = {n: info[n]["min"] >= 0 and info[n]["max"] > 1 for n in info}
        spd = speed if speed in info else laps.pick_speed(list(info), good)
        have = [n for n in names if n in info and n not in (rpm_name, spd)]
        want = [rpm_name, *([spd] if spd else []), *have]
        t, arr = _window(sid, want, None, None)
        kmh = laps.to_mps(arr[spd], info[spd]["unit"]) * 3.6 if spd else None
        ranges = pulls.find_pulls(t, arr[rpm_name], slope, min_span)
        table = pulls.pull_table(t, arr[rpm_name], kmh, ranges)
        logs[sid] = {"label": rec["label"], "started_at": rec.get("started_at"), "pulls": table, "speed_channel": spd,
                     "units": {n: info[n]["unit"] for n in have}}
        if not ranges:
            continue
        keep = {r["n"] for r in table if (f"{sid}:{r['n']}" in chosen if chosen else True)}
        runs.append({"key": sid, "t": t, "rpm": arr[rpm_name], "speed_kmh": kmh, "cols": {n: arr[n] for n in have},
                     "ranges": ranges, "selected": keep})
    out: dict = {"logs": logs, "skipped": skipped, "compare": None}
    if runs and any(r["selected"] for r in runs):
        try:
            out["compare"] = pulls.compare(runs, bin, mass_kg)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
    out["units"] = {n: u for l in logs.values() for n, u in l["units"].items()}
    return out


@app.get("/api/lapcompare")
def lap_compare(
    sources: str = Query(..., description="comma-separated log ids"),
    channels: str = Query(..., description="comma-separated channel names"),
    selected: str = Query("", description="lap keys like id:3, comma-separated; default is every valid lap"),
    ref: str = "",
    axis: str = Query("distance", pattern="^(distance|time)$"),
    points: int = Query(600, ge=50, le=3000),
    q: LapQuery = Depends(),
) -> dict:
    """Laps from several logs on one overlay, compared against one reference lap."""
    names = [x for x in channels.split(",") if x][:6]
    ids = [x for x in sources.split(",") if x][:12]
    if not names or not ids:
        raise HTTPException(422, "Choose at least one log and one channel")
    runs, tables, skipped = _collect_runs(ids, names, q, {x for x in selected.split(",") if x})
    best = min(((r["key"], l) for r in runs for l in r["laps"]), key=lambda kl: kl[1]["duration_s"])
    rk, _, rn = ref.partition(":")
    ref_pair = (rk, int(rn)) if rn.isdigit() and rk in {r["key"] for r in runs} else (best[0], best[1]["n"])
    try:
        out = laps.overlay_runs(runs, ref_pair, axis, points)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    out["best"] = {"log": best[0], "n": best[1]["n"]}
    out["logs"] = tables
    out["skipped"] = skipped
    out["units"] = {n: u for t in tables.values() for n, u in t["units"].items()}
    return out


@app.get("/api/sources/{source_id}/track")
def source_track(
    source_id: str, color: str | None = None, mirror: bool = False, q: LapQuery = Depends()
) -> dict:
    extra = [color] if color else []
    c = _lap_context(source_id, q, extra, need_laps=False)  # a track can be drawn without laps
    bounds, table = c["bounds"], c["table"]
    pos, cols, info = c["pos"], c["cols"], c["info"]
    try:
        path = laps.track_path(
            c["t"],
            laps.to_mps(cols[c["speed"]], info[c["speed"]]["unit"]) if c["speed"] else None,
            cols[pos[0]] if pos else None,
            cols[pos[1]] if pos else None,
            cols.get("gpsCourse"),
            cols.get("latG"),
            mirror,
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    if color:
        v = cols[color]
        path["color"] = [None if not np.isfinite(x) else float(x) for x in v[path["index"]]]
        path["color_unit"] = info[color]["unit"]
    if c["dist"] is not None:  # lets the screen place a chart cursor on the track
        path["dist"] = [float(x) for x in c["dist"][path["index"]]]
    path["boundaries"] = bounds
    path["best"] = table["best"]
    path["laps"] = [{"n": l["n"], "t_start": l["t_start"], "t_end": l["t_end"]} for l in table["laps"]]
    del path["index"]
    return path


# --- serve the built frontend, if present --------------------------------------------------
_DIST = store.REPO_ROOT / "frontend" / "dist"
if _DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "unknown API route")
        candidate = _DIST / path
        if path and candidate.is_file() and _DIST in candidate.resolve().parents:
            return FileResponse(candidate)
        # revalidate the page every load so a rebuilt bundle (new hashed filename) is picked up
        return FileResponse(_DIST / "index.html", headers={"Cache-Control": "no-cache"})
