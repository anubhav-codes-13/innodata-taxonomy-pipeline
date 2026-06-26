"""Phase 3/4 enrichment, wired for the per-file pipeline.

Turns a document's retrieval chunks into the L1-L4 taxonomy:

    route (L1 domain + L2 topic)        Phase 3.1   src.phase3.router
      -> L3 sub-topics (cluster+label)  Phase 3.3   src.phase3.l3_discovery
      -> L4 entities + keywords         Phase 3.2   src.phase3.l4_extractor
      -> synthesize document record     Phase 4     src.phase4.synthesize

The expensive bits — the master dictionary and the provider objects
(embedder / generator / extractor / namer) — are built once and cached in an
`EnrichmentContext`, then reused across every file in a batch.

Providers resolve from config.ENRICH_PROVIDER:
  * "auto"   -> real Gemini when an API key is present, else offline dummies
  * "gemini" -> force Gemini (needs GOOGLE_API_KEY / GEMINI_API_KEY)
  * "dummy"  -> force deterministic offline providers (demo-safe, no key)

This mirrors `src.phase3.run_full_poc.process_document` (route + L4) and adds
the optional L3 layer plus the Phase 4 synthesis roll-up.
"""
from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path

from .config import BASE_DIR, ENABLE_L3, ENRICH_PROVIDER, MASTER_DICT_PATH

logger = logging.getLogger("insight_engine.enrichment")

# Guarded imports of the sibling `src/` packages, mirroring pipeline.py: keep
# the API importable even if they're missing, and surface a clear error only
# when enrichment is actually attempted (via _build_context).
try:  # pragma: no cover - import shim
    from src.phase3.l3_discovery import discover_l3_for_l2, group_by_l2
    from src.phase3.l4_extractor import L4ExtractionNode
    from src.phase3.providers import make_embedder, make_extractor, make_generator, make_namer
    from src.phase3.router import TopicRouter
    from src.phase4.synthesize import synthesize_document
    _IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover
    discover_l3_for_l2 = group_by_l2 = None  # type: ignore
    L4ExtractionNode = TopicRouter = None  # type: ignore
    make_embedder = make_extractor = make_generator = make_namer = None  # type: ignore
    synthesize_document = None  # type: ignore
    _IMPORT_ERROR = exc


@dataclass
class EnrichmentContext:
    """Reusable, batch-scoped providers + master dictionary."""
    master: dict
    router: object          # TopicRouter
    l4_node: object         # L4ExtractionNode
    embedder: object        # for L3 clustering
    namer: object           # for L3 labelling
    enable_l3: bool
    provider_label: str     # e.g. "gemini" / "dummy" — for logging


_CTX: EnrichmentContext | None = None
_CTX_LOCK = threading.Lock()


def _resolve_kinds() -> tuple[str, str, str, str, str]:
    """Return (embedder, generator, extractor, namer, label) provider kinds."""
    choice = ENRICH_PROVIDER
    if choice == "auto":
        has_key = bool(
            os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
        )
        choice = "gemini" if has_key else "dummy"

    if choice in ("gemini", "google", "google-gemini"):
        return ("gemini", "google", "google", "google", "gemini")
    if choice == "dummy":
        return ("dummy", "dummy", "dummy", "dummy", "dummy")
    raise ValueError(
        f"Unknown IE_ENRICH_PROVIDER={ENRICH_PROVIDER!r} "
        "(expected 'auto', 'gemini', or 'dummy')."
    )


def _build_context() -> EnrichmentContext:
    import json

    if _IMPORT_ERROR is not None:
        raise RuntimeError(
            "Enrichment unavailable: src.phase3/phase4 could not be imported "
            f"({type(_IMPORT_ERROR).__name__}: {_IMPORT_ERROR})."
        )

    # Pick up GOOGLE_API_KEY / GEMINI_API_KEY from a project .env before we
    # decide between real and dummy providers in "auto" mode.
    try:  # pragma: no cover - optional dependency, present in this env
        from dotenv import load_dotenv

        load_dotenv(BASE_DIR / ".env")
    except Exception:
        pass

    master_path = Path(MASTER_DICT_PATH)
    if not master_path.is_file():
        raise FileNotFoundError(
            f"Master dictionary not found at {master_path}. Set IE_MASTER_DICT "
            "to a valid master_dictionary.json."
        )
    master = json.loads(master_path.read_text(encoding="utf-8"))

    emb_kind, gen_kind, ext_kind, namer_kind, label = _resolve_kinds()
    embedder = make_embedder(emb_kind)
    generator = make_generator(gen_kind)
    extractor = make_extractor(ext_kind)
    namer = make_namer(namer_kind)

    router = TopicRouter(master, embedder, generator)   # auto threshold
    l4_node = L4ExtractionNode(master, extractor)

    logger.info(
        "Enrichment context ready: provider=%s, master=%s, L3=%s",
        label, master_path.name, "on" if ENABLE_L3 else "off",
    )
    return EnrichmentContext(
        master=master, router=router, l4_node=l4_node, embedder=embedder,
        namer=namer, enable_l3=ENABLE_L3, provider_label=label,
    )


def get_context() -> EnrichmentContext:
    """Build (once) and return the shared enrichment context.

    Thread-safe; the heavy provider construction happens on first use only.
    Raises with a clear message when providers/dictionary can't be set up.
    """
    global _CTX
    if _CTX is not None:
        return _CTX
    with _CTX_LOCK:
        if _CTX is None:
            _CTX = _build_context()
    return _CTX


# --- Stages (each operates on one document's chunk list) ------------------

def route_chunks(ctx: EnrichmentContext, chunks: list[dict]) -> list[dict]:
    """Phase 3.1 — assign L1 domain + L2 topic to each chunk.

    Each route() yields 1..N RouterResults; for a single doc all chunks share
    the same L1 path, so we take the first result. Chunks with no known
    cust_group route to nothing and pass through unchanged.
    """
    routed: list[dict] = []
    for c in chunks:
        results = ctx.router.route(c)
        routed.append(results[0].chunk if results else c)
    return routed


def discover_l3(ctx: EnrichmentContext, chunks: list[dict]) -> list[dict]:
    """Phase 3.3 — cluster each L2 bucket and label sub-topics (optional).

    Degrades gracefully: any failure logs a warning and returns the input
    unchanged, so a flaky clustering/naming step never fails the document.
    """
    if not ctx.enable_l3:
        return chunks
    try:
        groups = group_by_l2(chunks)
        l3_by_chunk: dict[str, dict] = {}
        for l2_topic, bucket in groups.items():
            labelled, _audits = discover_l3_for_l2(
                bucket, l2_topic, ctx.embedder, ctx.namer
            )
            for lc in labelled:
                cid = lc.get("chunk_id")
                if not cid:
                    continue
                l3_by_chunk[cid] = {
                    k: lc[k] for k in ("L3_Sub_Topic", "L3_Source") if k in lc
                }
        if not l3_by_chunk:
            return chunks
        out: list[dict] = []
        for c in chunks:
            extra = l3_by_chunk.get(c.get("chunk_id"))
            out.append({**c, **extra} if extra else c)
        return out
    except Exception as exc:  # noqa: BLE001 — L3 is best-effort
        logger.warning("L3 discovery skipped (%s: %s)", type(exc).__name__, exc)
        return chunks


def extract_l4(ctx: EnrichmentContext, chunks: list[dict],
               retry_failed_once: bool = True) -> list[dict]:
    """Phase 3.2 — extract L4 entities + keywords per chunk.

    One retry pass for transient provider failures (Gemini occasionally
    returns an unparseable response on the first try).
    """
    enriched: list[dict] = []
    needs_retry: list[int] = []
    for i, c in enumerate(chunks):
        r = ctx.l4_node.extract(c)
        enriched.append(r.chunk)
        if r.status != "EXTRACTED":
            needs_retry.append(i)

    if retry_failed_once and needs_retry:
        for i in needs_retry:
            r = ctx.l4_node.extract(enriched[i])
            if r.status == "EXTRACTED":
                enriched[i] = r.chunk
    return enriched


def synthesize(doc_id: str, chunks: list[dict],
               parsed_doc: dict | None = None) -> dict:
    """Phase 4 — roll a document's enriched chunks into the L1-L4 taxonomy."""
    return synthesize_document(doc_id, chunks, parsed_doc=parsed_doc).to_dict()
