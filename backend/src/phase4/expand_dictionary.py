"""
Build an enriched dictionary from the fully-processed chunk store.

The original master_dictionary.json is the ANCHOR set handed to Phase 3.1:
the seed taxonomy + whatever editorial tags came from the XML. It freezes
what the router was told to anchor against.

After the full pipeline runs, the L4 extractor has proposed thousands of
new keywords, the L2 router has expanded many new macro-topics, and the
L3 clusterer has named every L2 cluster. None of that flows back into the
master dictionary — which is the whole "what does the corpus look like
now?" question this module answers.

Inputs:
  - enriched_chunks.json  (Phase 3 output: chunks carrying L1/L2/L3/L4)
  - master_dictionary.json (Phase 2 output: seeds + harvested editorial tags)

Output: enriched_dictionary.json with the shape:

  {
    "KA":  {
      "topics_seed":          {id: text},          # from master_dictionary
      "topics_discovered":    {name: chunk_count}, # new L2s the router expanded
      "l3_sub_topics":        {name: chunk_count}, # every L3 name seen
      "keywords_seed":        [...],               # from master_dictionary
      "keywords_matched":     {kw: chunk_count},   # seeds that L4 matched against
      "keywords_discovered":  {kw: chunk_count}    # novel L4 keywords
    },
    "KCL": { same shape },
    "global_entities": {
      "organizations":             [...],
      "countries":                 [...],
      "case_names":                {name: chunk_count},
      "statutes_and_regulations":  {name: chunk_count}
    },
    "_summary": {
      "total_chunks": N, "total_docs": N,
      "KA":  {... counts ...},
      "KCL": {... counts ...},
      "global_entities": {... counts ...}
    }
  }

Case-folded dedup (reuse phase4.synthesize._casefold_dedup):
  - All list-valued outputs have duplicates like "European Commission" and
    "european commission" collapsed to the best-cased single entry.
  - For dict-valued outputs (name → count), the counts of colliding
    variants are summed under the best-cased key.

Usage:
    python -m src.phase4.expand_dictionary \\
        --chunks data/poc_output/enriched_chunks.json \\
        --master data/poc_output/master_dictionary.json \\
        --out    data/poc_output/enriched_dictionary.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from .synthesize import _casefold_dedup, _title_case_score


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# cust_group → domain key. Same mapping the router uses. Duplicated here
# because we don't want a Phase-3 import inside Phase 4 for a 2-line map.
_CUST_GROUP_TO_DOMAIN: dict[str, str] = {"KA": "KA", "KCL": "KCL"}


def _chunk_domain_key(chunk: dict) -> str | None:
    """Route a chunk to its domain bucket.

    Priority:
      1. L1_Domain (display label) if we can map it — defends against
         chunks whose cust_groups were dropped somewhere downstream.
      2. First known cust_group.
    Unknown → None (caller's problem).
    """
    l1 = chunk.get("L1_Domain")
    if isinstance(l1, str):
        if l1 == "International Arbitration":
            return "KA"
        if l1 == "Competition Law":
            return "KCL"
    for cg in chunk.get("cust_groups") or []:
        if cg in _CUST_GROUP_TO_DOMAIN:
            return _CUST_GROUP_TO_DOMAIN[cg]
    return None


def _merge_counters_casefold(counter: Counter) -> dict[str, int]:
    """Collapse Counter keys by case-folding; keep the best-cased
    representative (via _title_case_score) and sum colliding counts.

    Returns a plain dict, sorted by count desc then name asc so the
    output JSON is stable across runs.
    """
    groups: dict[str, dict] = {}  # casefold_key -> {best, score, upper, count}
    for raw, n in counter.items():
        if not raw or not isinstance(raw, str):
            continue
        s = raw.strip()
        if not s:
            continue
        key = s.casefold()
        score = _title_case_score(s)
        upper = sum(1 for ch in s if ch.isupper())
        entry = groups.get(key)
        if entry is None:
            groups[key] = {"best": s, "score": score, "upper": upper, "count": n}
            continue
        entry["count"] += n
        # Apply the same "better representative" rule as _casefold_dedup.
        if score > entry["score"]:
            entry["best"], entry["score"], entry["upper"] = s, score, upper
        elif score == entry["score"] and upper > entry["upper"]:
            entry["best"], entry["upper"] = s, upper

    # Sort by count desc, then name asc.
    items = sorted(
        ((g["best"], g["count"]) for g in groups.values()),
        key=lambda kv: (-kv[1], kv[0].casefold()),
    )
    return dict(items)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def build_enriched_dictionary(chunks: list[dict],
                              master: dict) -> dict:
    """Pure function: assemble the enriched dictionary structure.

    Kept library-friendly (no argparse/IO) so this can be called from a
    notebook or another script that already has the loaded data in hand.
    """
    # Seed material straight from the anchor dictionary.
    seed_ka  = (master.get("KA")  or {})
    seed_kcl = (master.get("KCL") or {})
    seed_global = (master.get("global_entities") or {})

    # Per-domain counters.
    l2_discovered: dict[str, Counter] = {"KA": Counter(), "KCL": Counter()}
    l3_seen:       dict[str, Counter] = {"KA": Counter(), "KCL": Counter()}
    kw_matched:    dict[str, Counter] = {"KA": Counter(), "KCL": Counter()}
    kw_new:        dict[str, Counter] = {"KA": Counter(), "KCL": Counter()}

    # Global entity counters (not domain-bound — a court or statute is the
    # same real-world thing regardless of the practice area).
    global_orgs:     Counter = Counter()
    global_cases:    Counter = Counter()
    global_statutes: Counter = Counter()

    # Track which L2 names were ANCHORED (already in seed) vs EXPANDED.
    # The chunk's L2_Source tells us; but we also check against the seed
    # topic texts to be safe (router may be reconfigured, we trust the data).
    ka_seed_topic_texts  = {v.strip() for v in (seed_ka.get("topics")  or {}).values() if v}
    kcl_seed_topic_texts = {v.strip() for v in (seed_kcl.get("topics") or {}).values() if v}
    seed_topic_texts = {"KA": ka_seed_topic_texts, "KCL": kcl_seed_topic_texts}

    docs_seen: set[str] = set()

    for c in chunks:
        domain = _chunk_domain_key(c)
        if not domain:
            continue
        doc_id = c.get("doc_id")
        if doc_id:
            docs_seen.add(doc_id)

        # L2: only count in "discovered" if the name isn't a literal seed
        # topic text. Avoids inflating "discovered" with anchor hits.
        l2 = (c.get("L2_Topic") or "").strip()
        if l2 and l2 not in seed_topic_texts[domain]:
            l2_discovered[domain][l2] += 1

        # L3: every L3 name is fair game — the whole taxonomy level is
        # pipeline-generated.
        l3 = (c.get("L3_Sub_Topic") or "").strip()
        if l3:
            l3_seen[domain][l3] += 1

        # L4.
        md = c.get("L4_metadata") or {}
        ents = md.get("entities") or {}
        kws  = md.get("keywords") or {}

        for s in (ents.get("organizations") or []):
            s = (s or "").strip()
            if s: global_orgs[s] += 1
        for s in (ents.get("case_names") or []):
            s = (s or "").strip()
            if s: global_cases[s] += 1
        for s in (ents.get("statutes_and_regulations") or []):
            s = (s or "").strip()
            if s: global_statutes[s] += 1

        for s in (kws.get("existing_matched_keywords") or []):
            s = (s or "").strip()
            if s: kw_matched[domain][s] += 1
        for s in (kws.get("new_extracted_keywords") or []):
            s = (s or "").strip()
            if s: kw_new[domain][s] += 1

    # Assemble final structure with casefold-deduped counters.
    def domain_block(dom: str, seed_block: dict) -> dict:
        return {
            "topics_seed":         seed_block.get("topics") or {},
            "topics_discovered":   _merge_counters_casefold(l2_discovered[dom]),
            "l3_sub_topics":       _merge_counters_casefold(l3_seen[dom]),
            "keywords_seed":       list(seed_block.get("keywords") or []),
            "keywords_matched":    _merge_counters_casefold(kw_matched[dom]),
            "keywords_discovered": _merge_counters_casefold(kw_new[dom]),
        }

    ka_block  = domain_block("KA",  seed_ka)
    kcl_block = domain_block("KCL", seed_kcl)

    # Seed global entities come from master_dictionary as flat string lists.
    # We keep them deduped separately; the pipeline-derived counts live in
    # the same buckets as counters.
    seed_orgs = seed_global.get("organizations") or []
    seed_cnt  = seed_global.get("countries") or []

    global_block = {
        "organizations_seed":        _casefold_dedup(seed_orgs),
        "organizations_discovered":  _merge_counters_casefold(global_orgs),
        "countries_seed":            _casefold_dedup(seed_cnt),
        "case_names":                _merge_counters_casefold(global_cases),
        "statutes_and_regulations":  _merge_counters_casefold(global_statutes),
    }

    summary = {
        "total_chunks": len(chunks),
        "total_docs":   len(docs_seen),
        "KA": {k: len(v) for k, v in ka_block.items()},
        "KCL": {k: len(v) for k, v in kcl_block.items()},
        "global_entities": {k: len(v) for k, v in global_block.items()},
    }

    return {
        "KA":              ka_block,
        "KCL":             kcl_block,
        "global_entities": global_block,
        "_summary":        summary,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Build enriched dictionary from enriched chunks + seed master dictionary")
    ap.add_argument("--chunks", type=Path, required=True,
                    help="enriched_chunks.json (Phase 3 output)")
    ap.add_argument("--master", type=Path, required=True,
                    help="master_dictionary.json (Phase 2 output)")
    ap.add_argument("--out",    type=Path, required=True,
                    help="where to write enriched_dictionary.json")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    chunks = json.loads(args.chunks.read_text(encoding="utf-8"))
    master = json.loads(args.master.read_text(encoding="utf-8"))
    print(f"Loaded {len(chunks)} chunks + master_dictionary with domains "
          f"{[k for k in master if k != 'global_entities']}")

    enriched = build_enriched_dictionary(chunks, master)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(enriched, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    s = enriched["_summary"]
    print(f"\nWrote {args.out}")
    print(f"  chunks: {s['total_chunks']}   docs: {s['total_docs']}")
    for dom in ("KA", "KCL"):
        b = s[dom]
        print(f"  {dom}:")
        print(f"    topics      seed={b['topics_seed']:>4}   "
              f"discovered={b['topics_discovered']:>4}")
        print(f"    L3 sub-topics               = {b['l3_sub_topics']:>4}")
        print(f"    keywords    seed={b['keywords_seed']:>4}   "
              f"matched={b['keywords_matched']:>4}   "
              f"discovered={b['keywords_discovered']:>4}")
    ge = s["global_entities"]
    print(f"  global entities:")
    print(f"    organizations  seed={ge['organizations_seed']}  "
          f"discovered={ge['organizations_discovered']}")
    print(f"    countries seed = {ge['countries_seed']}")
    print(f"    case_names      = {ge['case_names']}")
    print(f"    statutes        = {ge['statutes_and_regulations']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
