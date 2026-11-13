import io
import json
import urllib.error

import pytest

from backend.app import briefing

REVIEW = {
    "findings": [
        {"severity": "high", "title": "Coolant drifts", "detail": "81.6 to 89.4 C at WOT", "channels": ["ect"], "count": 2},
        {"severity": "low", "title": "syncDiag on", "detail": "probably normal", "channels": ["syncDiag"], "count": 1},
    ]
}


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_only_attention_findings_are_sent(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    seen = {}

    def fake(req, timeout):
        seen["body"] = json.loads(req.data)
        return _Resp(json.dumps({"choices": [{"message": {"content": " Look at coolant. "}}]}).encode())

    monkeypatch.setattr(briefing.urllib.request, "urlopen", fake)
    out = briefing.brief(REVIEW)
    assert out["text"] == "Look at coolant." and out["findings"] == 1
    sent = json.loads(seen["body"]["messages"][1]["content"])
    assert [f["title"] for f in sent] == ["Coolant drifts"]


def test_nothing_to_explain_makes_no_call(monkeypatch):
    monkeypatch.setattr(briefing.urllib.request, "urlopen", lambda *a, **k: pytest.fail("called"))
    assert briefing.brief({"findings": []})["model"] is None


def test_missing_key_and_http_error(monkeypatch, tmp_path):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("LET_DATA_DIR", str(tmp_path))
    with pytest.raises(briefing.BriefingError, match="No Groq key"):
        briefing.brief(REVIEW)
    monkeypatch.setenv("GROQ_API_KEY", "k")

    def boom(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 401, "no", {}, None)

    monkeypatch.setattr(briefing.urllib.request, "urlopen", boom)
    with pytest.raises(briefing.BriefingError, match="401"):
        briefing.brief(REVIEW)
