"""Pydantic request/response models for the API.

These are the contract the React app builds against. FastAPI emits them into
the OpenAPI schema at /docs and /openapi.json, so a typed TS client can be
generated from them.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class FileFormat(str, Enum):
    xml = "xml"
    pdf = "pdf"
    docx = "docx"


class Domain(str, Enum):
    KA = "KA"      # Kluwer Arbitration  -> L1 "International Arbitration"
    KCL = "KCL"    # Kluwer Competition Law -> L1 "Competition Law"


class FileStatus(str, Enum):
    pending = "pending"          # uploaded, not yet part of a started batch
    queued = "queued"            # accepted for processing, not started yet
    parsing = "parsing"          # XML -> structured doc (src.rag_parser)
    chunking = "chunking"        # structured doc -> retrieval chunks
    routing = "routing"          # chunks -> L1 domain + L2 topic (Phase 3.1)
    enriching = "enriching"      # L3 sub-topics + L4 entities/keywords (Phase 3.2)
    synthesizing = "synthesizing"  # roll chunks up into the L1-L4 taxonomy (Phase 4)
    processing = "processing"    # generic in-flight (kept for back-compat)
    done = "done"
    failed = "failed"


class FileRecord(BaseModel):
    """One uploaded file as stored on the local device."""

    id: str
    filename: str
    size: int
    format: FileFormat
    content_type: str | None = None
    domain: Domain | None = None
    # True when the user must still choose a domain (PDF/DOC, or ambiguous XML).
    needs_domain: bool
    status: FileStatus
    # First page(s) of extracted text for PDF/DOC — shown on the Confirm screen.
    text_preview: str | None = None
    # How `domain` was set: "auto" (XML cust-group), "manual" (user), or None.
    domain_source: str | None = None
    created_at: datetime
    # Populated once processing reaches `done`; null until then.
    chunk_count: int | None = None
    # Human-readable failure reason when status == "failed".
    error: str | None = None


class FileUpdate(BaseModel):
    """PATCH body — assign a domain to a PDF/DOC (or correct an XML)."""

    domain: Domain


class ProcessRequest(BaseModel):
    """POST /api/process body — the set of uploaded files to run through the
    local parse -> chunk pipeline. Omit/empty to process everything pending."""

    file_ids: list[str] = []


class ProcessResponse(BaseModel):
    batch_id: str
    file_ids: list[str]


class StatusEvent(BaseModel):
    """One server-sent event payload streamed from GET /api/events."""

    id: str
    status: FileStatus
    chunk_count: int | None = None
    error: str | None = None


# --- Enriched document (taxonomy) -----------------------------------------
# The presentation contract the React Result/Document screens consume. The
# flat Phase-4 rollup (entities/keywords/provenance) plus a nested
# L1->L2->L3->L4 tree composed from the enriched chunks.


class TaxonomyNode(BaseModel):
    """One node in the L1->L4 taxonomy tree.

    L1/L2/L3 carry `label` (+ `source`/`similarity` provenance on L2). L4
    leaves carry `kind` (cases | statutes | organizations | keywords) and
    `values`.
    """

    level: str  # "L1" | "L2" | "L3" | "L4"
    label: str | None = None
    source: str | None = None       # L2 provenance: "anchor" | "generator"
    similarity: float | None = None  # L2 cosine against the matched anchor
    kind: str | None = None          # L4: "cases" | "statutes" | "organizations" | "keywords"
    values: list[str] | None = None  # L4 leaf values
    children: list["TaxonomyNode"] | None = None


class Provenance(BaseModel):
    summary: str
    anchored_pct: float = 0
    expanded_pct: float = 0


class Entities(BaseModel):
    case_names: list[str] = []
    statutes_and_regulations: list[str] = []
    organizations: list[str] = []


class Keywords(BaseModel):
    all: list[str] = []
    matched_from_dictionary: list[str] = []
    newly_extracted: list[str] = []


class DocumentDetail(BaseModel):
    doc_id: str
    filename: str
    doc_type: str
    domain: Domain
    container_title: str | None = None
    publ_year: int | None = None
    chunk_count: int
    case_metadata: dict | None = None
    provenance: Provenance
    taxonomy_tree: list[TaxonomyNode] = []
    entities: Entities
    keywords: Keywords


class DocumentSummary(BaseModel):
    """Lightweight row for the Batch-Results table + History list."""

    document_id: str
    filename: str
    domain: Domain
    doc_type: str
    top_topic: str
    levels: str = "L1-L4"
    processed_at: datetime
    chunk_count: int | None = None


class KeywordStat(BaseModel):
    """One row of the keyword-frequency dashboard: a keyword and the number of
    documents it appears in (highest first)."""

    keyword: str
    frequency: int


TaxonomyNode.model_rebuild()  # resolve the self-referential `children`
