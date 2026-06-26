"""Runtime configuration. All values override-able via environment variables.

Local-storage layout (created on startup):

    <repo>/storage/
    ├── uploads/                 raw uploaded files, named <file_id><ext>
    └── insight_engine.db        SQLite metadata index
"""
from __future__ import annotations

import os
from pathlib import Path

# Repo root = parent of the `api/` package.
BASE_DIR = Path(__file__).resolve().parent.parent

# --- Local device storage -------------------------------------------------
STORAGE_DIR = Path(os.getenv("IE_STORAGE_DIR", str(BASE_DIR / "storage")))
UPLOAD_DIR = STORAGE_DIR / "uploads"
DB_PATH = STORAGE_DIR / "insight_engine.db"
# Per-file retrieval chunks written by the parse -> chunk pipeline, one
# <file_id>.json per processed document.
CHUNK_DIR = STORAGE_DIR / "chunks"
# Enrichment outputs (Phase 3/4). Enriched chunks carry L1-L4 fields; the
# taxonomy file is the synthesized, presentation-ready document record.
ENRICHED_CHUNK_DIR = STORAGE_DIR / "enriched_chunks"  # <file_id>.json
ENRICHED_DIR = STORAGE_DIR / "enriched"               # <file_id>.json (taxonomy)

# --- Processing pipeline --------------------------------------------------
# Artificial pause inserted before each visible stage (parsing, chunking) so
# the live status stream is perceptible in the UI even though local parse +
# chunk finishes in milliseconds. Set IE_STAGE_DELAY_MS=0 to disable.
STAGE_DELAY_MS = int(os.getenv("IE_STAGE_DELAY_MS", "500"))

# How many files in a batch process concurrently. 1 = sequential (the original
# behaviour). Higher values overlap the per-file stages — a large win for the
# I/O-bound Gemini provider (parallel API calls); with the offline dummy
# provider the GIL caps CPU speedup but parse/IO still overlap. The shared
# EnrichmentContext (master dict + providers) is reused across all workers.
# Default 3 — a good fit for free-tier Gemini (keeps simultaneous LLM calls low
# enough to avoid rate-limit backoff). Raise via IE_MAX_CONCURRENCY for paid
# quota / the offline dummy provider; set 1 for sequential.
MAX_CONCURRENCY = max(1, int(os.getenv("IE_MAX_CONCURRENCY", "3")))

# --- Enrichment (Phase 3 routing/L3/L4 + Phase 4 synthesis) ---------------
# Master taxonomy dictionary (KA/KCL domains + global_entities). Override with
# IE_MASTER_DICT; otherwise use the first of these that exists on disk.
_MASTER_DICT_CANDIDATES = [
    BASE_DIR / "data" / "poc_output" / "master_dictionary.json",
    BASE_DIR / "data" / "rag_out" / "master_dictionary.json",
    BASE_DIR / "data" / "demo4" / "out" / "master_dictionary.json",
]
_master_env = os.getenv("IE_MASTER_DICT")
MASTER_DICT_PATH = (
    Path(_master_env) if _master_env
    else next((p for p in _MASTER_DICT_CANDIDATES if p.is_file()),
              _MASTER_DICT_CANDIDATES[0])
)

# Provider selection for enrichment LLM/embeddings:
#   "auto"   -> Gemini when GOOGLE_API_KEY/GEMINI_API_KEY is set, else dummy
#   "gemini" -> force real Gemini providers (requires an API key)
#   "dummy"  -> force offline deterministic providers (no key, demo-safe)
ENRICH_PROVIDER = os.getenv("IE_ENRICH_PROVIDER", "auto").lower()

# L3 sub-topic discovery (cluster-then-label) is optional; it adds the L3 layer
# but is the most expensive stage. Set IE_ENABLE_L3=0 to skip it.
ENABLE_L3 = os.getenv("IE_ENABLE_L3", "1").strip().lower() not in ("0", "false", "no")

# --- Upload validation ----------------------------------------------------
MAX_FILE_SIZE_MB = int(os.getenv("IE_MAX_FILE_SIZE_MB", "25"))
MAX_FILE_SIZE = MAX_FILE_SIZE_MB * 1024 * 1024
# .doc maps to the docx format bucket (legacy binary; preview is best-effort).
ALLOWED_EXTENSIONS = {".xml", ".pdf", ".doc", ".docx"}

# Characters of extracted text returned as a preview for PDF/DOC files.
PREVIEW_CHARS = 400

# --- CORS (React dev servers) --------------------------------------------
CORS_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "IE_CORS_ORIGINS",
        "http://localhost:5173,http://localhost:5174,http://localhost:3000",
    ).split(",")
    if o.strip()
]
