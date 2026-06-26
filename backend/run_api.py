"""Dev launcher for the API with a correctly-scoped auto-reloader.

`uvicorn api.main:app --reload` watches the entire working directory — which
includes `api/.venv`. Under OneDrive (this repo lives in a synced folder), sync
constantly touches site-packages `.py` files, and every touch triggers a
reload that interrupts the previous one mid-import. The result is an endless
"WatchFiles detected changes ... Reloading" / KeyboardInterrupt storm.

This launcher watches only the source packages (`api/` and `src/`) and excludes
the virtualenv, so reloads fire on *your* edits only.

Run it with the venv's Python:

    api/.venv/Scripts/python.exe run_api.py

Override host/port/provider via the usual env vars, e.g.:

    IE_ENRICH_PROVIDER=gemini  api/.venv/Scripts/python.exe run_api.py
"""
from __future__ import annotations

import os
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / "api" / ".venv"

if __name__ == "__main__":
    uvicorn.run(
        "api.main:app",
        host=os.getenv("IE_HOST", "127.0.0.1"),
        port=int(os.getenv("IE_PORT", "8000")),
        reload=True,
        # Watch source only — NOT the repo root (which contains api/.venv).
        reload_dirs=[str(ROOT / "api"), str(ROOT / "src")],
        # Absolute dir path so uvicorn's exclude_dirs containment check matches
        # every file under the virtualenv (globs can't target a nested dir).
        reload_excludes=[str(VENV_DIR)],
    )
