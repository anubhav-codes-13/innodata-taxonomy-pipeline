"""Local parse -> chunk -> enrich pipeline, run once per uploaded file.

Drives each file through visible status transitions

    queued -> parsing -> chunking -> routing -> enriching -> synthesizing
        -> done                                          (or -> failed)

persisting the status to the store and publishing an event on the bus after
every transition, so SSE subscribers (`GET /api/events`) see the progression
live.

Scope: only XML is parsed today — `src.rag_parser` handles the KLI KEA-BASIC
schema and `src.semantic_chunker` turns the parsed doc into retrieval chunks.
PDF/DOCX uploads fail fast with a clear message until their extractors are
wired in. The enrichment stages (Phase 3 routing/L3/L4 + Phase 4 synthesis,
in `api.enrichment`) produce the L1-L4 taxonomy; they run with offline dummy
providers by default and switch to Gemini automatically when an API key is
present (see `config.ENRICH_PROVIDER`).
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from . import enrichment, store
from .config import (
    CHUNK_DIR,
    ENRICHED_CHUNK_DIR,
    ENRICHED_DIR,
    MAX_CONCURRENCY,
    STAGE_DELAY_MS,
)
from .events import bus

logger = logging.getLogger("insight_engine.pipeline")

# Live count of files currently being processed (between worker START/END).
# Exposed via /api/health so parallelism is observable in the browser without
# relying on console logs.
_INFLIGHT = 0


def inflight_count() -> int:
    return _INFLIGHT

# parse_file / chunk_document live in the sibling `src/` package (importable
# when the API is launched from the repo root). Import lazily-guarded so the
# app still boots if that package is missing; processing then fails per-file
# with a clear message instead of crashing import of the whole API.
try:  # pragma: no cover - import shim
    from src.rag_parser import parse_file as _parse_file
    from src.semantic_chunker import chunk_document as _chunk_document
except Exception:  # pragma: no cover
    _parse_file = None
    _chunk_document = None


def _emit(file_id: str, status: str, **extra) -> None:
    """Persist a status transition and broadcast it to SSE subscribers."""
    store.set_status(file_id, status, **extra)
    bus.publish({"id": file_id, "status": status, **extra})


async def _pause() -> None:
    """Brief, visible pause between stages (configurable; 0 disables)."""
    if STAGE_DELAY_MS > 0:
        await asyncio.sleep(STAGE_DELAY_MS / 1000)


async def process_file(file_id: str) -> None:
    rec = store.get_file(file_id)
    path_str = store.get_stored_path(file_id)
    if rec is None or path_str is None:
        return  # deleted between scheduling and running

    if _parse_file is None or _chunk_document is None:
        _emit(file_id, "failed",
              error="Pipeline unavailable: src.rag_parser/semantic_chunker "
                    "could not be imported.")
        return

    if rec.format.value != "xml":
        _emit(file_id, "failed",
              error=f"{rec.format.value.upper()} parsing is not implemented "
                    "yet (only XML runs through the pipeline today).")
        return

    path = Path(path_str)
    try:
        await _pause()
        _emit(file_id, "parsing")
        doc = await asyncio.to_thread(_parse_file, path)
        if doc is None:
            _emit(file_id, "failed",
                  error="Could not parse XML (invalid or unrecognised "
                        "KEA-BASIC document).")
            return

        # Log the full parsed JSON for each document as it comes through.
        logger.info(
            "Parsed document %s (file_id=%s, doc_type=%s, doc_id=%s):\n%s",
            getattr(path, "name", path),
            file_id,
            doc.get("doc_type"),
            doc.get("doc_id"),
            json.dumps(doc, ensure_ascii=False, indent=2),
        )

        await _pause()
        _emit(file_id, "chunking")
        chunks = await asyncio.to_thread(lambda: list(_chunk_document(doc)))

        CHUNK_DIR.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(
            (CHUNK_DIR / f"{file_id}.json").write_text,
            json.dumps(chunks, ensure_ascii=False, indent=2),
            "utf-8",
        )

        # --- Enrichment: route (L1/L2) -> L3 -> L4 -> synthesize ---
        # Built once and reused across the batch; a setup failure (missing
        # master dict, or Gemini requested without a key) surfaces as failed.
        ctx = await asyncio.to_thread(enrichment.get_context)
        doc_id = doc.get("doc_id") or file_id

        await _pause()
        _emit(file_id, "routing")
        enriched = await asyncio.to_thread(enrichment.route_chunks, ctx, chunks)

        await _pause()
        _emit(file_id, "enriching")
        enriched = await asyncio.to_thread(enrichment.discover_l3, ctx, enriched)
        enriched = await asyncio.to_thread(enrichment.extract_l4, ctx, enriched)

        ENRICHED_CHUNK_DIR.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(
            (ENRICHED_CHUNK_DIR / f"{file_id}.json").write_text,
            json.dumps(enriched, ensure_ascii=False, indent=2),
            "utf-8",
        )

        await _pause()
        _emit(file_id, "synthesizing")
        taxonomy = await asyncio.to_thread(
            enrichment.synthesize, doc_id, enriched, doc
        )

        ENRICHED_DIR.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(
            (ENRICHED_DIR / f"{file_id}.json").write_text,
            json.dumps(taxonomy, ensure_ascii=False, indent=2),
            "utf-8",
        )

        # Log the synthesized L1-L4 taxonomy for each document.
        logger.info(
            "Enriched document %s (file_id=%s, doc_id=%s, provider=%s):\n%s",
            getattr(path, "name", path),
            file_id,
            doc_id,
            ctx.provider_label,
            json.dumps(taxonomy, ensure_ascii=False, indent=2),
        )

        # Record this document's keywords for the cross-document frequency
        # dashboard (idempotent — replaces any prior set for this file).
        kw_block = (taxonomy.get("taxonomy") or {}).get("L4_Keywords") or {}
        dom = rec.domain.value if rec.domain else None
        await asyncio.to_thread(
            store.set_document_keywords, file_id, kw_block.get("all") or [], dom
        )

        _emit(file_id, "done", chunk_count=len(chunks))
    except Exception as exc:  # noqa: BLE001 — any failure surfaces to the UI
        _emit(file_id, "failed", error=f"{type(exc).__name__}: {exc}")


async def run_batch(file_ids: list[str]) -> None:
    """Mark the whole set queued, then process up to MAX_CONCURRENCY files at
    once.

    Each file's blocking stages already run in `asyncio.to_thread`, so several
    files can overlap their parse / embed / LLM work while `_emit` stays on the
    event-loop thread (publishing to the SSE bus is loop-only by design). The
    shared EnrichmentContext is pre-built once here so workers don't each pay —
    or serialise on — first-use construction. MAX_CONCURRENCY=1 reproduces the
    original sequential behaviour.
    """
    logger.info(
        "Batch start: %d file(s), concurrency=%d", len(file_ids), MAX_CONCURRENCY
    )
    for fid in file_ids:
        _emit(fid, "queued")

    # Pre-warm the shared context (master dict + providers). A setup failure is
    # ignored here and re-surfaces per-file inside process_file as `failed`.
    try:
        await asyncio.to_thread(enrichment.get_context)
    except Exception:  # noqa: BLE001
        pass

    sem = asyncio.Semaphore(MAX_CONCURRENCY)

    async def worker(fid: str) -> None:
        global _INFLIGHT
        async with sem:
            _INFLIGHT += 1
            logger.info("worker START %s  (in-flight now: %d)", fid, _INFLIGHT)
            try:
                await process_file(fid)
            finally:
                _INFLIGHT -= 1
                logger.info("worker END   %s  (in-flight now: %d)", fid, _INFLIGHT)

    await asyncio.gather(*(worker(fid) for fid in file_ids))
