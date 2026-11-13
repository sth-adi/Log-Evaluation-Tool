"""A short plain-words briefing of the review findings, written by a Groq-hosted model.

Only the findings the checks already computed are sent (title, detail, channels, severity, how many
places). No raw log samples leave the computer, and the model is told to explain, not to add
findings of its own. The key comes from GROQ_API_KEY or data/groq_key.txt (data/ is git-ignored)."""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

from . import store

log = logging.getLogger(__name__)

URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
TIMEOUT_S = 30
MAX_FINDINGS = 12

SYSTEM = (
    "You brief a Formula Student engine and electronics team on automatic checks of their logged data. "
    "You get a JSON list of findings that were already computed. Explain them in plain words, most "
    "important first, in at most 120 words and no markdown. Say what to look at first and why. Use only "
    "what is in the findings: do not invent channels, numbers or causes, and say 'could be' when "
    "guessing at a cause. If nothing needs attention, say so in one sentence."
)


class BriefingError(RuntimeError):
    pass


def _key() -> str:
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        f = store.data_dir() / "groq_key.txt"
        if f.exists():
            key = f.read_text(encoding="utf-8").strip()
    if not key:
        raise BriefingError("No Groq key. Set GROQ_API_KEY or put it in data/groq_key.txt.")
    return key


def _payload(review: dict) -> list[dict]:
    keep = [f for f in review["findings"] if f["severity"] != "low"][:MAX_FINDINGS]
    return [
        {
            "severity": f["severity"],
            "title": f["title"],
            "detail": f["detail"],
            "channels": f["channels"][:6],
            "places": f["count"],
        }
        for f in keep
    ]


def brief(review: dict) -> dict:
    items = _payload(review)
    if not items:
        return {"text": "Nothing needs attention in the open logs.", "model": None, "findings": 0}
    body = json.dumps(
        {
            "model": MODEL,
            "temperature": 0.2,
            "max_tokens": 300,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": json.dumps(items)},
            ],
        }
    ).encode()
    req = urllib.request.Request(
        URL,
        data=body,
        headers={"Authorization": f"Bearer {_key()}", "Content-Type": "application/json", "User-Agent": "log-evaluation-tool"},
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            data = json.load(r)
        text = data["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        log.warning("Groq returned %s", e.code)
        raise BriefingError(f"Groq refused the request ({e.code}).") from e
    except (urllib.error.URLError, TimeoutError) as e:
        log.warning("Groq unreachable: %s", e)
        raise BriefingError("Could not reach Groq.") from e
    except (KeyError, IndexError, ValueError) as e:
        raise BriefingError("Groq sent back something unexpected.") from e
    return {"text": text, "model": MODEL, "findings": len(items)}
