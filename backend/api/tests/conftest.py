"""Pytest fixtures for the API tests.

The storage dir is redirected to a temp location BEFORE any `api` module is
imported (config binds paths at import time), so tests never touch the real
./storage. Each test runs against a clean files table + empty uploads dir.
"""
import os
import tempfile

# Must run before `api.config` is imported anywhere.
os.environ.setdefault("IE_STORAGE_DIR", tempfile.mkdtemp(prefix="ie_test_"))

import sqlite3

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="session")
def client():
    # `with` triggers lifespan -> creates the storage dir + SQLite table.
    from api.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _clean_state():
    """Wipe the files table + uploads dir before every test."""
    from api import config, store

    store.init_db()
    with sqlite3.connect(config.DB_PATH) as cx:
        cx.execute("DELETE FROM files")
    if config.UPLOAD_DIR.exists():
        for p in config.UPLOAD_DIR.iterdir():
            if p.is_file():
                p.unlink()
    yield
