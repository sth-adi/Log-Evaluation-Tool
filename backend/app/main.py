"""FastAPI application: import logs, list sources, serve downsampled signals.

Run (from the repo root):
    python -m uvicorn backend.app.main:app --port 8000
The built frontend (frontend/dist) is served from the same port when present.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import analysis, lifeview, report, store
from .downsample import minmax_downsample
from .derived import FormulaError
from .importer import ImportErrorDetail, parse_csv

MAX_UPLOAD_BYTES = 512 * 1024 * 1024
KINDS = {"ecu", "hcu", "other"}

app = FastAPI(title="Log Evaluation Tool", version="0.1.0")


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


@app.post("/api/arrange")
def arrange(body: ArrangeBody) -> list[dict]:
    """Order logs by session start time (as LifeView does) and set their time offsets."""
    if body.mode not in ("sequential", "real"):
        raise HTTPException(422, "mode must be 'sequential' or 'real'")
    return store.arrange_sources(body.mode, max(body.gap_s, 0.0))


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
