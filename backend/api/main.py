"""FastAPI application entrypoint.

Run from the repo root:

    uvicorn api.main:app --reload

Interactive docs: http://localhost:8000/docs
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__, pipeline, store
from .config import CORS_ORIGINS, ENRICH_PROVIDER, MAX_CONCURRENCY, UPLOAD_DIR
from .routers import documents, files, process


def _configure_logging() -> None:
    """Make our `insight_engine.*` loggers actually emit.

    uvicorn only attaches handlers to its own `uvicorn.*` loggers, so a custom
    logger would propagate to the unconfigured root logger (default level
    WARNING, no handler) and INFO lines would be dropped. Reuse uvicorn's
    handlers when present so output/format matches; fall back to basicConfig
    for non-uvicorn runs (tests, `python -m ...`).
    """
    app_logger = logging.getLogger("insight_engine")
    if app_logger.handlers:  # already configured (e.g. --reload re-import)
        return

    uvicorn_logger = logging.getLogger("uvicorn")
    if uvicorn_logger.handlers:
        app_logger.handlers = uvicorn_logger.handlers
    else:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
    app_logger.setLevel(logging.INFO)
    app_logger.propagate = False  # handlers attached directly; avoid dupes


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure logging emits, and local storage + metadata DB exist before serving.
    _configure_logging()
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    store.init_db()
    # Backfill keyword frequencies for any docs enriched before the table existed.
    try:
        from . import documents
        documents.backfill_keywords()
    except Exception:  # pragma: no cover — never block startup on backfill
        pass
    yield


app = FastAPI(
    title="Insight Engine API",
    version=__version__,
    summary="Upload legal documents and enrich them with a 4-level taxonomy.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(files.router, prefix="/api")
app.include_router(process.router, prefix="/api")
app.include_router(documents.router, prefix="/api")


@app.get("/api/health", tags=["meta"])
def health() -> dict:
    return {
        "status": "ok",
        "version": __version__,
        # Diagnostics: confirm the running build's config + live parallelism.
        "max_concurrency": MAX_CONCURRENCY,
        "enrich_provider": ENRICH_PROVIDER,
        "inflight": pipeline.inflight_count(),
    }


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request, exc: StarletteHTTPException):
    """Consistent error envelope: { "error": { "code", "message" } }."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.status_code, "message": exc.detail}},
    )
