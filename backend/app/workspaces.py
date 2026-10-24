"""Saved views: the plots, tab and lap settings someone set up, kept as small JSON files.

A view names channels, never log ids, so it applies to whichever logs are open when it is loaded.
The server only stores and returns the payload; the browser decides what it means.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timezone

from . import store

log = logging.getLogger(__name__)

MAX_BYTES = 100_000
MAX_NAME = 80
_ID = re.compile(r"^[0-9a-f]{10}$")


def _dir():
    d = store.data_dir() / "workspaces"
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_all() -> list[dict]:
    out = []
    for f in _dir().glob("*.json"):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError) as e:  # one damaged file should not hide the others, but it must not vanish quietly
            log.warning("saved view %s is unreadable and was skipped: %s", f.name, e)
    return sorted(out, key=lambda w: w.get("saved_at", ""), reverse=True)


def save(name: str, payload: dict) -> dict:
    name = " ".join(name.split())[:MAX_NAME]
    if not name:
        raise ValueError("Give the view a name")
    if len(json.dumps(payload)) > MAX_BYTES:
        raise ValueError("That view is too large to save")
    existing = next((w for w in list_all() if w["name"].lower() == name.lower()), None)
    rec = {
        "id": existing["id"] if existing else uuid.uuid4().hex[:10],
        "name": name,
        "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "payload": payload,
    }
    (_dir() / f"{rec['id']}.json").write_text(json.dumps(rec), encoding="utf-8")
    return rec


def delete(view_id: str) -> None:
    if not _ID.match(view_id):
        raise KeyError(view_id)
    f = _dir() / f"{view_id}.json"
    if not f.is_file():
        raise KeyError(view_id)
    f.unlink()
