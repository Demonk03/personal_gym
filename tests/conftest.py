import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from app import create_app
from db import MemoryRepository


@pytest.fixture
def demo_program():
    return json.loads((ROOT / "tests/fixtures/demo_program.json").read_text())


@pytest.fixture
def repository(demo_program):
    return MemoryRepository(demo_program)


@pytest.fixture
def client(monkeypatch, repository):
    monkeypatch.setenv("API_KEY", "test-key")
    monkeypatch.setenv("DASHBOARD_ORIGIN", "https://gym.example,http://localhost:8000")
    return create_app(repository=repository).test_client()


@pytest.fixture
def auth():
    return {"Authorization": "Bearer test-key"}
