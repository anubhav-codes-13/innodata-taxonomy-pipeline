"""Compose presentation-ready document records from persisted enrichment.

Reads two artifacts written by the pipeline:

  storage/enriched/<file_id>.json         Phase-4 rollup (flat: L2 lists, L3
                                          list, L4 entity/keyword sets,
                                          provenance, case_metadata)
  storage/enriched_chunks/<file_id>.json  per-chunk L1-L4 (carries the L2->L3
                                          mapping + L2_Source/L2_Similarity)

The Explorer needs a nested L1->L2->L3->L4 tree, which only exists at the
chunk level (the Phase-4 rollup is flat). `build_tree` composes it by grouping
the document's enriched chunks by L2 then L3 and aggregating L4 leaves — the
composition called out in API_REQUIREMENTS.md §5.
"""
from __future__ import annotations

import json
from collections import OrderedDict
from pathlib import Path

from . import store
from .config import ENRICHED_CHUNK_DIR, ENRICHED_DIR

# Reuse the pipeline's case-folding dedup so entity/keyword surface forms match
# the rest of the system; fall back to a simple dedup if it can't be imported.
try:  # pragma: no cover - import shim
    from src.phase4.synthesize import _casefold_dedup as _dedup_impl
except Exception:  # pragma: no cover
    _dedup_impl = None

_L1_TO_DOMAIN = {"International Arbitration": "KA", "Competition Law": "KCL"}


def _dedup(items: list[str]) -> list[str]:
    vals = [x for x in items if x]
    if _dedup_impl is not None:
        try:
            return _dedup_impl(vals)
        except Exception:
            pass
    seen: dict[str, str] = {}
    for v in vals:
        seen.setdefault(v.casefold(), v)
    return list(seen.values())


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _l4_leaves(chunks: list[dict]) -> list[dict]:
    """Aggregate L4 entities + keywords across a set of chunks into leaf nodes."""
    cases: list[str] = []
    statutes: list[str] = []
    orgs: list[str] = []
    kws: list[str] = []
    for c in chunks:
        l4 = c.get("L4_metadata") or {}
        ents = l4.get("entities") or {}
        kw = l4.get("keywords") or {}
        cases += ents.get("case_names") or []
        statutes += ents.get("statutes_and_regulations") or []
        orgs += ents.get("organizations") or []
        kws += (kw.get("existing_matched_keywords") or []) + (kw.get("new_extracted_keywords") or [])
    leaves: list[dict] = []
    for kind, vals in (("cases", cases), ("statutes", statutes), ("organizations", orgs), ("keywords", kws)):
        deduped = _dedup(vals)
        if deduped:
            leaves.append({"level": "L4", "kind": kind, "values": deduped})
    return leaves


def build_tree(enriched_chunks: list[dict], taxonomy: dict) -> list[dict]:
    """Compose the nested L1->L2->L3->L4 tree from enriched chunks."""
    if not enriched_chunks:
        return []
    l1_label = taxonomy.get("L1_Domain") or enriched_chunks[0].get("L1_Domain")
    if not l1_label:
        return []

    # Order L2 buckets by the rollup's ranking (word-weight desc); any L2 not
    # in the rollup list still gets appended via setdefault below.
    order = [t.get("l2_topic") for t in taxonomy.get("L2_All_Topics", []) if t.get("l2_topic")]
    by_l2: "OrderedDict[str, list[dict]]" = OrderedDict((name, []) for name in order)
    for c in enriched_chunks:
        l2 = c.get("L2_Topic")
        if not l2:
            continue
        by_l2.setdefault(l2, []).append(c)

    l2_nodes: list[dict] = []
    for l2, group in by_l2.items():
        if not group:
            continue
        source = (
            "anchor" if any(c.get("L2_Source") == "anchor" for c in group)
            else "generator" if any(c.get("L2_Source") == "generator" for c in group)
            else None
        )
        sims = [c.get("L2_Similarity") for c in group if isinstance(c.get("L2_Similarity"), (int, float))]
        similarity = round(max(sims), 3) if sims else None

        by_l3: "OrderedDict[str | None, list[dict]]" = OrderedDict()
        for c in group:
            by_l3.setdefault(c.get("L3_Sub_Topic"), []).append(c)

        children: list[dict] = []
        for l3, sub in by_l3.items():
            leaves = _l4_leaves(sub)
            if l3:
                children.append({"level": "L3", "label": l3, "children": leaves})
            else:
                # No L3 for these chunks — attach the L4 leaves directly to L2.
                children.extend(leaves)

        l2_nodes.append({
            "level": "L2", "label": l2, "source": source,
            "similarity": similarity, "children": children,
        })

    return [{"level": "L1", "label": l1_label, "children": l2_nodes}]


def _domain_for(rec, taxonomy: dict) -> str:
    if rec is not None and rec.domain is not None:
        return rec.domain.value
    return _L1_TO_DOMAIN.get(taxonomy.get("L1_Domain"), "KA")


def _top_topic(taxonomy: dict) -> str:
    primary = taxonomy.get("L2_Primary_Topics") or []
    if primary:
        return primary[0].get("l2_topic") or ""
    all_topics = taxonomy.get("L2_All_Topics") or []
    return (all_topics[0].get("l2_topic") or "") if all_topics else ""


def build_detail(file_id: str) -> dict | None:
    """Full DocumentDetail dict for one processed file, or None if not enriched."""
    record = _read_json(ENRICHED_DIR / f"{file_id}.json")
    if record is None:
        return None
    taxonomy = record.get("taxonomy") or {}
    enriched_chunks = _read_json(ENRICHED_CHUNK_DIR / f"{file_id}.json") or []
    rec = store.get_file(file_id)

    prov = taxonomy.get("L2_Provenance") or {}
    entities = taxonomy.get("L4_Entities") or {}
    keywords = taxonomy.get("L4_Keywords") or {}

    return {
        "doc_id": record.get("doc_id") or file_id,
        "filename": rec.filename if rec else (record.get("doc_id") or file_id),
        "doc_type": record.get("doc_type") or "document",
        "domain": _domain_for(rec, taxonomy),
        "container_title": record.get("container_title"),
        "publ_year": record.get("publ_year"),
        "chunk_count": record.get("chunk_count") or len(enriched_chunks),
        "case_metadata": record.get("case_metadata"),
        "provenance": {
            "summary": prov.get("summary", "N/A"),
            "anchored_pct": prov.get("anchored_pct", 0),
            "expanded_pct": prov.get("expanded_pct", 0),
        },
        "taxonomy_tree": build_tree(enriched_chunks, taxonomy),
        "entities": {
            "case_names": entities.get("case_names", []),
            "statutes_and_regulations": entities.get("statutes_and_regulations", []),
            "organizations": entities.get("organizations", []),
        },
        "keywords": {
            "all": keywords.get("all", []),
            "matched_from_dictionary": keywords.get("matched_from_dictionary", []),
            "newly_extracted": keywords.get("newly_extracted", []),
        },
    }


def topic_frequencies(
    level: str,
    domain: str | None = None,
    search: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """Topic label → document-frequency for L1, L2, or L3.

    Scans the enriched-chunk JSON files for all done documents (optionally
    filtered by domain) and counts how many documents contain each unique label
    at the requested level.  Returns [{"keyword": label, "frequency": n}, …]
    sorted by frequency desc (same shape as keyword_frequencies so the
    dashboard can reuse the same chart component).
    """
    with_domain = domain is not None

    # Collect (file_id, domain) pairs for done documents.
    file_pairs: list[tuple[str, str | None]] = []
    for rec in store.list_files():
        if rec.status.value != "done":
            continue
        doc_domain = rec.domain.value if rec.domain else None
        if with_domain and doc_domain != domain:
            continue
        file_pairs.append((rec.id, doc_domain))

    counter: dict[str, int] = {}
    for file_id, _ in file_pairs:
        chunk_path = ENRICHED_CHUNK_DIR / f"{file_id}.json"
        if not chunk_path.is_file():
            # Also try the taxonomy JSON for L1 (it has L1_Domain at top level)
            if level == "L1":
                tax_path = ENRICHED_DIR / f"{file_id}.json"
                rec_json = _read_json(tax_path)
                if rec_json:
                    taxonomy = rec_json.get("taxonomy") or {}
                    l1 = taxonomy.get("L1_Domain")
                    if l1:
                        counter[l1] = counter.get(l1, 0) + 1
            continue
        chunks = _read_json(chunk_path) or []

        seen: set[str] = set()
        for c in chunks:
            if level == "L1":
                v = c.get("L1_Domain")
            elif level == "L2":
                v = c.get("L2_Topic")
            elif level == "L3":
                v = c.get("L3_Sub_Topic")
            else:
                v = None
            if v and v not in seen:
                seen.add(v)
                counter[v] = counter.get(v, 0) + 1

    if search:
        sq = search.lower()
        counter = {k: v for k, v in counter.items() if sq in k.lower()}

    items = sorted(counter.items(), key=lambda x: (-x[1], x[0]))[:limit]
    return [{"keyword": label, "frequency": freq} for label, freq in items]


def backfill_keywords() -> int:
    """Populate document_keywords for any processed file missing from it.

    Lets the keyword dashboard reflect documents enriched before the table
    existed (or before this build), without reprocessing. Incremental: skips
    files already recorded. Returns how many files were backfilled.
    """
    have = store.keyworded_file_ids()
    n = 0
    for rec in store.list_files():
        if rec.status.value != "done" or rec.id in have:
            continue
        record = _read_json(ENRICHED_DIR / f"{rec.id}.json")
        if record is None:
            continue
        taxonomy = record.get("taxonomy") or {}
        keywords = ((taxonomy.get("L4_Keywords") or {}).get("all")) or []
        store.set_document_keywords(rec.id, keywords, _domain_for(rec, taxonomy))
        n += 1
    return n


def list_summaries() -> list[dict]:
    """Lightweight summary for every processed (done) file."""
    out: list[dict] = []
    for rec in store.list_files():
        if rec.status.value != "done":
            continue
        record = _read_json(ENRICHED_DIR / f"{rec.id}.json")
        if record is None:
            continue
        taxonomy = record.get("taxonomy") or {}
        out.append({
            "document_id": rec.id,
            "filename": rec.filename,
            "domain": _domain_for(rec, taxonomy),
            "doc_type": record.get("doc_type") or "document",
            "top_topic": _top_topic(taxonomy),
            "levels": "L1-L4",
            "processed_at": rec.created_at,
            "chunk_count": rec.chunk_count,
        })
    return out
