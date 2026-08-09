from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

TEST_ROOT = Path("local_data/test-runtime")
if TEST_ROOT.exists():
    shutil.rmtree(TEST_ROOT)
TEST_ROOT.mkdir(parents=True, exist_ok=True)
os.environ["APP_ENV"] = "test"
os.environ["APP_AUTH_MODE"] = "demo"
os.environ["APP_DEMO_TOKEN"] = "demo-token"
os.environ["PROVIDER_MODE"] = "mock"
os.environ["GOOGLE_CLOUD_STORAGE_BUCKET"] = ""
os.environ["GOOGLE_PUBSUB_TOPIC"] = ""
os.environ["CLICKHOUSE_URL"] = ""
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_ROOT / 'test.sqlite3'}"
os.environ["STORAGE_ROOT"] = str(TEST_ROOT / "media")

from apps.api.app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer demo-token"}
