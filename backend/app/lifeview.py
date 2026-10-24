"""Convert Life Racing .LRD logs to CSV by driving LifeView's own CSV export, then import them.

.LRD files are encrypted and only LifeView can read them. This does not read or decrypt them; it
operates LifeView's File > export To > Text File (CSV) the way a person would, using the scripts in
tools/lifeview. Windows only, and LifeView must be installed.

One conversion runs at a time, in a background thread: LifeView takes over the mouse and keyboard
for a few seconds per log, so two at once would collide.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import store
from .importer import ImportErrorDetail, parse_csv

TOOLS_DIR = store.REPO_ROOT / "tools" / "lifeview"
LIFEVIEW_EXE = Path(os.environ.get("LIFEVIEW_EXE", r"C:\Program Files (x86)\Life Racing\LifeView.exe"))
MAX_LRD_BYTES = 256 * 1024 * 1024

Progress = Callable[[str], None]
Runner = Callable[[Path, Progress], Path]  # (.LRD path, progress callback) -> CSV path


class Busy(RuntimeError):
    """A conversion is already running."""


def status() -> dict:
    """Whether conversion can run on this machine, and if not, why in plain words."""
    if sys.platform != "win32":
        return {"available": False, "reason": "Converting .LRD files needs Windows with LifeView installed."}
    if not LIFEVIEW_EXE.exists():
        return {
            "available": False,
            "reason": f"LifeView was not found at {LIFEVIEW_EXE}. Install it, or set LIFEVIEW_EXE to its location.",
        }
    try:
        import psutil  # noqa: F401
        import win32gui  # noqa: F401
    except ImportError:
        return {"available": False, "reason": "Missing Python packages. Run: pip install pywin32 psutil"}
    return {"available": True, "reason": ""}


def _tools():
    if str(TOOLS_DIR) not in sys.path:
        sys.path.insert(0, str(TOOLS_DIR))
    import lv_export_all as allmod  # noqa: PLC0415
    import lv_export_csv as ex  # noqa: PLC0415

    return allmod, ex


def lifeview_running() -> bool:
    if not status()["available"]:
        return False
    return bool(_tools()[1].lifeview_pids())


def lifeview_runner(lrd: Path, progress: Progress) -> Path:
    """Open the log in a fresh LifeView, switch on every channel, export CSV, close LifeView."""
    allmod, ex = _tools()
    if ex.lifeview_pids():
        raise RuntimeError("LifeView is already open. Close it, then try again.")
    try:
        progress("Opening in LifeView")
        allmod.open_log(str(lrd))
        progress("Switching channels on")
        ex.activate_all()
        progress("Exporting")
        try:
            ex.main(force=True, log=str(lrd))
        except SystemExit as e:  # the script reports failure by exiting with a message
            raise RuntimeError(str(e.code or "LifeView export failed")) from None
    finally:
        allmod.close_lifeview()
    csv = lrd.with_name(lrd.stem + " ALL.csv")
    if not csv.exists():
        raise RuntimeError("LifeView did not produce a CSV file.")
    return csv


RUNNER: Runner = lifeview_runner  # tests replace this


@dataclass
class Item:
    name: str
    state: str = "waiting"  # waiting | working | done | failed | skipped
    stage: str = ""
    error: str = ""
    source_id: str = ""
    csv: str = ""  # where the exported CSV was kept

    def public(self) -> dict:
        return {k: getattr(self, k) for k in ("name", "state", "stage", "error", "source_id", "csv")}


@dataclass
class Job:
    id: str
    items: list[Item]
    state: str = "running"  # running | done | cancelled
    cancel: bool = False
    started: float = field(default_factory=time.time)

    def public(self) -> dict:
        return {
            "id": self.id,
            "state": self.state,
            "items": [i.public() for i in self.items],
            "imported": sum(1 for i in self.items if i.state == "done"),
            "elapsed_s": round(time.time() - self.started, 1),
        }


_lock = threading.Lock()
_jobs: dict[str, Job] = {}
_current: Job | None = None


def get(job_id: str) -> Job:
    job = _jobs.get(job_id)
    if job is None:
        raise KeyError(job_id)
    return job


def cancel(job_id: str) -> Job:
    job = get(job_id)
    job.cancel = True  # takes effect between logs; a log that is mid-export finishes first
    return job


def start(files: list[tuple[str, bytes]]) -> Job:
    """Queue .LRD files (name, bytes) for conversion. Raises Busy if one is already running."""
    global _current
    with _lock:
        if _current is not None and _current.state == "running":
            raise Busy("A conversion is already running.")
        tmp = Path(tempfile.mkdtemp(prefix="let_lrd_"))
        paths: list[Path] = []
        items: list[Item] = []
        for name, data in files:
            safe = Path(name).name  # the session start time lives in the file name, so keep it
            (tmp / safe).write_bytes(data)
            paths.append(tmp / safe)
            items.append(Item(name=safe))
        job = Job(id=uuid.uuid4().hex[:10], items=items)
        _jobs[job.id] = job
        _current = job
    threading.Thread(target=_run, args=(job, paths, tmp), daemon=True).start()
    return job


def _run(job: Job, paths: list[Path], tmp: Path) -> None:
    exports = store.data_dir() / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    try:
        for item, lrd in sorted(zip(job.items, paths), key=lambda p: p[0].name):
            if job.cancel:
                item.state = "skipped"
                continue
            item.state = "working"
            try:
                csv = RUNNER(lrd, lambda s, it=item: setattr(it, "stage", s))
                item.stage = "Importing"
                kept = exports / csv.name
                shutil.copyfile(csv, kept)
                item.csv = str(kept)
                parsed = parse_csv(kept.read_bytes(), None, csv.name)
                rec = store.create_source(parsed.df, parsed.meta, lrd.stem, "other", csv.name)
                item.source_id = rec["id"]
                item.state, item.stage = "done", ""
            except ImportErrorDetail as e:
                item.state, item.error = "failed", f"The export could not be read: {e}"
            except Exception as e:  # keep going with the other logs
                item.state, item.error = "failed", str(e) or e.__class__.__name__
        job.state = "cancelled" if job.cancel else "done"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
