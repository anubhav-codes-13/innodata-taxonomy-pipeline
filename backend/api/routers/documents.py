"""Enriched-document read endpoints (the Result / History screens).

    GET /api/documents                      summaries of every processed file
    GET /api/files/{id}/document            full DocumentDetail (L1-L4 tree)
    GET /api/files/{id}/taxonomy            raw Phase-4 rollup (debug)
    GET /api/files/{id}/enriched-chunks     raw enriched chunks (debug)

These serve the artifacts the pipeline persists under storage/enriched/ and
storage/enriched_chunks/. `document` composes the nested taxonomy tree from the
chunks (see api/documents.py).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import documents, store
from ..config import ENRICHED_CHUNK_DIR, ENRICHED_DIR
from ..schemas import DocumentDetail, DocumentSummary, KeywordStat

router = APIRouter(tags=["documents"])


@router.get("/documents", response_model=list[DocumentSummary])
def list_documents() -> list[dict]:
    return documents.list_summaries()


@router.get("/keywords", response_model=list[KeywordStat])
def list_keywords(
    domain: str | None = None,
    search: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """Cross-document keyword frequency (highest first) for the dashboard."""
    return store.keyword_frequencies(domain=domain, search=search, limit=limit)


@router.get("/topic-stats", response_model=list[KeywordStat])
def topic_stats(
    level: str = "L2",
    domain: str | None = None,
    search: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """Topic label frequency for L1/L2/L3 — same shape as /keywords."""
    if level not in ("L1", "L2", "L3"):
        level = "L2"
    return documents.topic_frequencies(level=level, domain=domain, search=search, limit=limit)


@router.get("/files/{file_id}/document", response_model=DocumentDetail)
def get_document(file_id: str) -> dict:
    detail = documents.build_detail(file_id)
    if detail is None:
        raise HTTPException(
            status_code=404,
            detail="No enriched taxonomy for this file (not processed yet).",
        )
    return detail


@router.get("/files/{file_id}/taxonomy")
def get_taxonomy(file_id: str) -> dict:
    rec = documents._read_json(ENRICHED_DIR / f"{file_id}.json")
    if rec is None:
        raise HTTPException(status_code=404, detail="No taxonomy for this file.")
    return rec


@router.get("/files/{file_id}/enriched-chunks")
def get_enriched_chunks(file_id: str) -> list[dict]:
    data = documents._read_json(ENRICHED_CHUNK_DIR / f"{file_id}.json")
    if data is None:
        raise HTTPException(status_code=404, detail="No enriched chunks for this file.")
    return data
