import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))


@pytest.fixture(scope="session")
def synthetic():
    import generate_logs

    return generate_logs.simulate(laps=2, seed=3)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LET_DATA_DIR", str(tmp_path))
    from fastapi.testclient import TestClient

    from backend.app.main import app

    return TestClient(app)
