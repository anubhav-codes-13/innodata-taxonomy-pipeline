"""
Phase 4 — Chunk-to-Document rollup for the Wolters Kluwer POC.

Reads the fully-enriched chunk JSON produced by Phase 3 (L1_Domain,
L2_Topic, L3_Sub_Topic, L4_metadata on every chunk) and rolls it back up
to the document level, producing `final_enriched_documents.json`.

Each document output contains:

  doc_id, doc_type, container_title, publ_year, cust_groups, [case_metadata]
  taxonomy:
    L1_Domain
    L2_Primary_Topics     (top 1–2 most frequent L2s across the doc's chunks)
    L2_All_Topics         (every L2 seen, with chunk counts)
    L3_Sub_Topics         (every unique L3 across the doc's chunks)
    L4_Entities:
      case_names, statutes_and_regulations, organizations   (deduped + sorted)
    L4_Keywords:
      all                  (existing_matched ∪ new_extracted, deduped + sorted)
      matched_from_dictionary
      newly_extracted
  chunk_count

Optional CLI flag:
  --compare <doc_id>   Prints a screenshot-friendly Before (original XML tags
                       from parsed_docs.json) vs After (synthesized taxonomy)
                       side-by-side for the POC presentation.

Usage:
  python -m src.phase4.synthesize \\
      --chunks  data/phase4/enriched_chunks.json \\
      --parsed  data/rag_out/ka_parsed.json data/rag_out/kcl_parsed.json \\
      --out     data/phase4/final_enriched_documents.json \\
      [--compare KLI-JOIA-420501]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable


# ---------------------------------------------------------------------------
# Primary-topic selection policy
# ---------------------------------------------------------------------------

# A candidate L2 is "primary" if its chunk count is within this ratio of
# the leader. With ratio=0.5, an L2 that appears in >=50% as many chunks
# as the leader qualifies for co-primary status. Keeps ties + near-ties.
_PRIMARY_MIN_RATIO: float = 0.5

# Hard cap on primary topics returned. 2 matches the spec ("top 1 or 2").
_PRIMARY_MAX: int = 2


def _select_primary_topics(l2_weight: Counter,
                           l2_counter: Counter) -> list[dict]:
    """Return the top 1–2 primary L2 topics, ranked by word weight.

    Weight-based ranking is more faithful to the document's actual content
    distribution than raw chunk count — a single 800-word chunk on Merger
    Control should dominate over two 40-word chunks on Cartels. Chunks
    don't have uniform voting power; words do.

    Rules:
      - Primary candidates are L2s whose word weight is
        >= leader_weight * _PRIMARY_MIN_RATIO.
      - Ranking is: word_weight desc, chunk_count desc, name asc (all three
        used deterministically so identical docs synthesise identically).
      - Result capped at _PRIMARY_MAX.

    `l2_counter` is required for the chunk_count field and the secondary
    tie-break — the two Counters are always accumulated together by
    synthesize_document.
    """
    if not l2_weight:
        return []
    # Rank by weight, but we also need chunk_count for output / tie-break.
    ranked = l2_weight.most_common()
    top_weight = ranked[0][1]
    threshold = top_weight * _PRIMARY_MIN_RATIO
    primary_candidates = sorted(
        [name for name, w in ranked if w >= threshold],
        key=lambda name: (-l2_weight[name], -l2_counter[name], name),
    )[:_PRIMARY_MAX]
    return [{
        "l2_topic":    name,
        "chunk_count": l2_counter[name],
        "word_weight": l2_weight[name],
    } for name in primary_candidates]


# ---------------------------------------------------------------------------
# Record shape
# ---------------------------------------------------------------------------

@dataclass
class DocumentSynthesis:
    """Presentation-ready document record."""
    doc_id:           str
    doc_type:         str | None
    container_title:  str | None
    publ_year:        int | None
    cust_groups:      list[str]
    case_metadata:    dict | None
    taxonomy:         dict
    chunk_count:      int

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Rollup logic
# ---------------------------------------------------------------------------

# The semantic_chunker emits `fused_text` as:
#     "[Container: ... | Document: ... | Section: ...]\n\n<body text>"
# For L2 word-weighting we want the *body* length, not the lineage
# breadcrumb — otherwise every chunk gets the same ~20-word inflation
# which shifts raw weights without affecting ranking. When the delimiter
# isn't present (e.g. chunks from a different chunker) we fall back to
# counting the whole string.
_BREADCRUMB_DELIMITER = "]\n\n"


def _chunk_body_words(chunk: dict) -> int:
    """Word count of a chunk's body text, stripping the lineage breadcrumb."""
    text = chunk.get("fused_text") or ""
    if not text:
        return 0
    # Breadcrumb always starts with '[' in our chunker. If it does AND the
    # delimiter is present, everything after the delimiter is the body.
    if text.startswith("[") and _BREADCRUMB_DELIMITER in text:
        _, _, body = text.partition(_BREADCRUMB_DELIMITER)
        return len(body.split())
    # Unknown shape — fall back to counting the whole string.
    return len(text.split())


def _dominant_l1(l1_counter: Counter) -> tuple[str | None, bool]:
    """Pick the dominant L1 for a document.

    Usually one L1 per doc (since cust_groups is stable at doc level). If
    multiple L1s appear (a multi-domain doc — cust_groups like ["KA","KCL"]),
    we still return the most frequent and flag the mixed state to the caller
    via the second return value.
    """
    if not l1_counter:
        return None, False
    ranked = l1_counter.most_common()
    mixed = len(ranked) > 1
    return ranked[0][0], mixed


def _summarise_l2_provenance(chunks: list[dict]) -> dict:
    """Count how each chunk's L2 was obtained (anchor vs generator).

    The router stamps chunks with L2_Source ∈ {"anchor", "generator",
    "generator_error"}. This rollup reports the anchored-vs-expanded
    split at the document level — lets the POC prove that the routing
    gate saves LLM calls whenever the seed dictionary already covers a
    concept.

    Returns a dict with absolute counts, percentages (rounded to 1dp for
    display) and a `summary` string pre-rendered for the CLI / screenshots.
    Chunks missing L2_Source are tracked separately under `unknown_count`
    so they don't inflate either side.
    """
    anchored = 0
    expanded = 0
    errored = 0
    unknown = 0

    for c in chunks:
        src = c.get("L2_Source")
        if src == "anchor":
            anchored += 1
        elif src == "generator":
            expanded += 1
        elif src == "generator_error":
            errored += 1
        else:
            unknown += 1

    considered = anchored + expanded  # the denominator for the display %
    if considered == 0:
        anchored_pct = 0.0
        expanded_pct = 0.0
        summary = "N/A (no routed chunks)"
    else:
        anchored_pct = round(100.0 * anchored / considered, 1)
        expanded_pct = round(100.0 - anchored_pct, 1)
        if anchored == considered:
            summary = "100% Anchored"
        elif expanded == considered:
            summary = "100% Expanded"
        else:
            summary = (f"Mixed: {anchored_pct:g}% Anchored, "
                       f"{expanded_pct:g}% Expanded")

    out: dict = {
        "summary": summary,
        "anchored_count": anchored,
        "expanded_count": expanded,
        "total":          considered,
        "anchored_pct":   anchored_pct,
        "expanded_pct":   expanded_pct,
    }
    # Surface error/unknown counts only when non-zero to keep the common
    # case tidy. Anyone auditing routing failures will look for these.
    if errored:
        out["generator_error_count"] = errored
    if unknown:
        out["unknown_source_count"] = unknown
    return out


# Short English stopwords that conventionally stay lowercase inside a
# title-cased phrase (editorial style). "of the" should survive
# uppercasing only at the start of a phrase. Keeping this list small
# and targeted — not trying to be a full NLP title-caser.
_TITLE_LOWER_STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "and", "as", "at", "but", "by", "for", "in", "of", "on",
    "or", "the", "to", "v", "vs", "via",
})


def _title_case_score(s: str) -> int:
    """Higher is "more editorial-looking title case".

    Per word:
      +1 if the word's capitalisation matches standard title-case rules
          (first word: TitleCase; later stopwords: lowercase; later
          content words: TitleCase).
      0 otherwise.

    Used as the primary tie-breaker inside `_casefold_dedup`. Deliberately
    simple — we don't need perfect stylistic judgement, just enough to
    prefer "Singapore Court of Appeal" over "Singapore Court Of Appeal"
    and "European Commission" over "european commission".
    """
    words = s.split()
    if not words:
        return 0
    score = 0
    for idx, word in enumerate(words):
        if not word:
            continue
        core = word.strip(".,;:!?()[]'\"")
        if not core:
            continue
        is_stopword = core.lower() in _TITLE_LOWER_STOPWORDS and idx != 0
        if is_stopword:
            if core == core.lower():
                score += 1
        else:
            # Content word: first char upper, rest not shouting.
            # "Court" passes; "court" and "COURT" and "Court Of" do not.
            if core[0].isupper() and core[1:] == core[1:].lower():
                score += 1
    return score


def _casefold_dedup(items: list[str]) -> list[str]:
    """Deduplicate a list of strings case-insensitively, keep the best form.

    The LLM extractor occasionally returns the same entity with different
    capitalisation across chunks (e.g. "European Commission" vs
    "european commission", or "Singapore Court of Appeal" vs
    "Singapore Court Of Appeal"). A naive `set()` keeps both and the
    final document JSON ends up with spurious duplicates.

    Strategy:
      - Group by casefold() key.
      - Within a group, pick the representative whose capitalisation best
        matches editorial title-case convention (_title_case_score).
      - Tie-break on the higher uppercase-character count (falls back to
        the older "more capitals wins" heuristic for strings with no
        obvious title-case structure, e.g. acronym-heavy statute IDs).
      - Further tie-break on earlier appearance in the input.
      - Empty / whitespace-only strings are dropped.

    The returned list is sorted case-insensitively so output ordering is
    intuitive regardless of which variant won the dedup.
    """
    groups: dict[str, dict] = {}  # casefold_key -> {best, score, upper, order}
    for order, raw in enumerate(items or []):
        if raw is None:
            continue
        s = str(raw).strip()
        if not s:
            continue
        key = s.casefold()
        score = _title_case_score(s)
        upper_count = sum(1 for ch in s if ch.isupper())
        entry = groups.get(key)
        if entry is None:
            groups[key] = {"best": s, "score": score,
                           "upper": upper_count, "order": order}
            continue
        # Replacement rule, cascading:
        #   1. strictly higher title-case score wins
        #   2. equal score, strictly more uppercase chars wins
        #      (helps when score ties at 0, e.g. "eumr" vs "EUMR")
        #   3. otherwise keep the earlier-seen representative
        better = False
        if score > entry["score"]:
            better = True
        elif score == entry["score"] and upper_count > entry["upper"]:
            better = True
        if better:
            entry["best"] = s
            entry["score"] = score
            entry["upper"] = upper_count
            # leave "order" so ordering ties stay stable
    return sorted((g["best"] for g in groups.values()), key=str.casefold)


def _merge_l4(chunks: list[dict]) -> dict:
    """Aggregate L4 entities + keywords across a doc's chunks.

    Entities and keywords are case-folded during dedup so "European
    Commission" and "european commission" collapse into a single entry
    whose surface form is the better-cased variant.

    Keywords: `existing_matched_keywords` (strings that came from the
    master dictionary) and `new_extracted_keywords` (model-proposed novel
    concepts) are surfaced separately AND combined into `all` for the
    common "show me every tag on this doc" use case. The `all` union is
    case-folded across both buckets to catch the matched/extracted drift
    case too.
    """
    # Collect as lists (preserves chunk order for first-seen tie-breaking)
    # rather than sets, because _casefold_dedup relies on input order.
    case_names: list[str]       = []
    statutes: list[str]         = []
    organizations: list[str]    = []
    matched_keywords: list[str] = []
    new_keywords: list[str]     = []

    for c in chunks:
        l4 = c.get("L4_metadata")
        if not l4:
            continue
        entities = (l4.get("entities") or {})
        case_names.extend(entities.get("case_names") or [])
        statutes.extend(entities.get("statutes_and_regulations") or [])
        organizations.extend(entities.get("organizations") or [])

        keywords = (l4.get("keywords") or {})
        matched_keywords.extend(keywords.get("existing_matched_keywords") or [])
        new_keywords.extend(keywords.get("new_extracted_keywords") or [])

    matched_final = _casefold_dedup(matched_keywords)
    new_final     = _casefold_dedup(new_keywords)
    # Union for `all`: case-fold across both bucket outputs so a keyword
    # that appears as "New York Convention" in one bucket and "new york
    # convention" in the other still counts once.
    all_keywords  = _casefold_dedup(matched_final + new_final)

    return {
        "entities": {
            "case_names":               _casefold_dedup(case_names),
            "statutes_and_regulations": _casefold_dedup(statutes),
            "organizations":            _casefold_dedup(organizations),
        },
        "keywords": {
            "all":                     all_keywords,
            "matched_from_dictionary": matched_final,
            "newly_extracted":         new_final,
        },
    }


def synthesize_document(doc_id: str, chunks: list[dict],
                        parsed_doc: dict | None = None) -> DocumentSynthesis:
    """Roll up a single document's chunks into one DocumentSynthesis record.

    `parsed_doc` is the corresponding entry from parsed_docs.json; when
    provided we pull document-level metadata (doc_type, container_title,
    etc.) from it so the output is self-describing. If absent we fall
    back to whatever the chunks carry.
    """
    l1_counter: Counter = Counter()
    l2_counter: Counter = Counter()   # chunk counts  (kept for transparency)
    l2_weight:  Counter = Counter()   # body-word weights (primary ranking)
    l3_set: set[str]    = set()
    cust_groups_set: set[str] = set()

    for c in chunks:
        l1 = c.get("L1_Domain")
        if l1: l1_counter[l1] += 1
        l2 = c.get("L2_Topic")
        if l2:
            l2_counter[l2] += 1
            # Accumulate word count so long chunks outweigh short ones.
            # A single 800-word section on one topic should beat two
            # 40-word asides on a different topic.
            l2_weight[l2] += _chunk_body_words(c)
        l3 = c.get("L3_Sub_Topic")
        if l3: l3_set.add(l3)
        for cg in c.get("cust_groups") or []:
            if cg: cust_groups_set.add(cg)

    primary_l1, mixed_l1 = _dominant_l1(l1_counter)

    if parsed_doc is not None:
        md = parsed_doc.get("metadata") or {}
        doc_type = parsed_doc.get("doc_type")
        container_title = md.get("container_title")
        publ_year = md.get("publ_year")
        case_metadata = parsed_doc.get("case_metadata")
    else:
        # Fallback when no parsed_doc supplied: derive what we can from chunks.
        doc_type = chunks[0].get("doc_type") if chunks else None
        container_title = None
        publ_year = None
        case_metadata = None

    # Rank all-topics by weight (same signal the primary selector uses),
    # falling back to chunk_count and then name for deterministic output.
    l2_all_sorted = sorted(
        l2_counter.keys(),
        key=lambda name: (-l2_weight[name], -l2_counter[name], name),
    )

    taxonomy: dict = {
        "L1_Domain": primary_l1,
        "L2_Primary_Topics": _select_primary_topics(l2_weight, l2_counter),
        "L2_All_Topics": [
            {"l2_topic": name,
             "chunk_count": l2_counter[name],
             "word_weight": l2_weight[name]}
            for name in l2_all_sorted
        ],
        "L2_Provenance": _summarise_l2_provenance(chunks),
        "L3_Sub_Topics": sorted(l3_set),
        **_merge_l4(chunks),  # L4_entities + L4_keywords nested in taxonomy
    }

    # Rename L4 block keys so the output structure is predictable.
    # _merge_l4 returns {"entities": ..., "keywords": ...}; we want them
    # under explicit L4_ names to mirror the spec vocabulary.
    taxonomy["L4_Entities"] = taxonomy.pop("entities")
    taxonomy["L4_Keywords"] = taxonomy.pop("keywords")

    if mixed_l1:
        taxonomy["_warning"] = (
            "Document has chunks in multiple L1 domains; selected the "
            "most frequent. Review cust_groups for correctness."
        )

    return DocumentSynthesis(
        doc_id=doc_id,
        doc_type=doc_type,
        container_title=container_title,
        publ_year=publ_year,
        cust_groups=sorted(cust_groups_set),
        case_metadata=case_metadata,
        taxonomy=taxonomy,
        chunk_count=len(chunks),
    )


def synthesize_corpus(chunks: list[dict],
                      parsed_docs_index: dict[str, dict] | None = None,
                      ) -> list[DocumentSynthesis]:
    """Group chunks by doc_id and synthesize each document."""
    by_doc: dict[str, list[dict]] = {}
    for c in chunks:
        did = c.get("doc_id")
        if not did:
            continue
        by_doc.setdefault(did, []).append(c)

    out: list[DocumentSynthesis] = []
    for did, dchunks in sorted(by_doc.items()):
        parsed = (parsed_docs_index or {}).get(did)
        out.append(synthesize_document(did, dchunks, parsed_doc=parsed))
    return out


# ---------------------------------------------------------------------------
# Before/After visualizer
# ---------------------------------------------------------------------------

def _wrap_lines(value: str | None, width: int) -> list[str]:
    """Wrap a string onto lines of <= width characters. Preserves word
    boundaries. Returns ['(none)'] for empty input — screenshot-friendly."""
    if not value:
        return ["(none)"]
    words = str(value).split()
    if not words:
        return ["(none)"]
    lines: list[str] = []
    current = ""
    for w in words:
        candidate = f"{current} {w}".strip() if current else w
        if len(candidate) > width:
            if current:
                lines.append(current)
            current = w
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _wrap_list(items: list[str] | None, width: int) -> list[str]:
    """Render a list of strings as one item per line, wrapping long ones."""
    if not items:
        return ["(none)"]
    out: list[str] = []
    for item in items:
        wrapped = _wrap_lines(f"• {item}", width)
        out.extend(wrapped)
    return out


def _side_by_side(left_title: str, left_lines: list[str],
                  right_title: str, right_lines: list[str],
                  col_width: int = 48) -> str:
    """Render two labelled columns with matching heights."""
    max_h = max(len(left_lines), len(right_lines))
    left_lines  = left_lines  + [""] * (max_h - len(left_lines))
    right_lines = right_lines + [""] * (max_h - len(right_lines))

    bar = "+" + "-" * (col_width + 2) + "+" + "-" * (col_width + 2) + "+"
    lines = [bar]
    lines.append(f"| {left_title:<{col_width}} | {right_title:<{col_width}} |")
    lines.append(bar)
    for l, r in zip(left_lines, right_lines):
        lines.append(f"| {l:<{col_width}} | {r:<{col_width}} |")
    lines.append(bar)
    return "\n".join(lines)


def _before_tags(parsed_doc: dict) -> dict:
    """Extract the 'Before' picture from parsed_docs.json."""
    enrichment = parsed_doc.get("enrichment") or {}
    topics = []
    for t in enrichment.get("topics") or []:
        if isinstance(t, dict):
            topics.append(f"{t.get('text') or ''} [{t.get('id') or '—'}]")
        else:
            topics.append(str(t))
    keywords = list(enrichment.get("keywords") or [])
    countries = [c.get("name") or c.get("code") for c in enrichment.get("countries") or []]
    organizations = [o.get("name") or o.get("code") for o in enrichment.get("organizations") or []]
    return {
        "topics":        [t for t in topics if t],
        "keywords":      [k for k in keywords if k],
        "countries":     [c for c in countries if c],
        "organizations": [o for o in organizations if o],
    }


def render_compare(doc_id: str, synthesis: DocumentSynthesis,
                   parsed_doc: dict, col_width: int = 48) -> str:
    """Produce the Before/After side-by-side block for `doc_id`.

    Designed for terminal screenshots: ASCII only, no colour codes, no
    emoji. If the terminal width is narrow, pass a smaller col_width.
    """
    title = (parsed_doc.get("metadata") or {}).get("title") or "(untitled)"
    before = _before_tags(parsed_doc)
    tax = synthesis.taxonomy

    # --- Before column ---
    before_lines: list[str] = []
    before_lines.append("TOPICS (editorial XML):")
    before_lines.extend(_wrap_list(before["topics"], col_width - 2))
    before_lines.append("")
    before_lines.append("KEYWORDS (editorial XML):")
    before_lines.extend(_wrap_list(before["keywords"], col_width - 2))
    before_lines.append("")
    before_lines.append("ORGANIZATIONS:")
    before_lines.extend(_wrap_list(before["organizations"], col_width - 2))
    before_lines.append("")
    before_lines.append("COUNTRIES:")
    before_lines.extend(_wrap_list(before["countries"], col_width - 2))

    # --- After column ---
    after_lines: list[str] = []
    after_lines.append(f"L1 DOMAIN:")
    after_lines.extend(_wrap_lines(tax.get("L1_Domain"), col_width - 2))
    after_lines.append("")
    after_lines.append("L2 PRIMARY TOPICS (chunks / word weight):")
    primary = [
        f"{p['l2_topic']} (x{p['chunk_count']}, {p['word_weight']}w)"
        for p in tax.get("L2_Primary_Topics") or []
    ]
    after_lines.extend(_wrap_list(primary, col_width - 2))
    after_lines.append("")
    prov = tax.get("L2_Provenance") or {}
    after_lines.append("L2 ROUTING PROVENANCE:")
    after_lines.extend(_wrap_lines(prov.get("summary"), col_width - 2))
    after_lines.append("")
    after_lines.append("L3 SUB-TOPICS:")
    after_lines.extend(_wrap_list(tax.get("L3_Sub_Topics"), col_width - 2))
    after_lines.append("")
    ents = tax.get("L4_Entities") or {}
    after_lines.append("L4 CASES:")
    after_lines.extend(_wrap_list(ents.get("case_names"), col_width - 2))
    after_lines.append("")
    after_lines.append("L4 STATUTES:")
    after_lines.extend(_wrap_list(ents.get("statutes_and_regulations"), col_width - 2))
    after_lines.append("")
    after_lines.append("L4 ORGANIZATIONS:")
    after_lines.extend(_wrap_list(ents.get("organizations"), col_width - 2))
    after_lines.append("")
    kw = tax.get("L4_Keywords") or {}
    after_lines.append(f"L4 KEYWORDS (matched {len(kw.get('matched_from_dictionary') or [])} / "
                       f"new {len(kw.get('newly_extracted') or [])}):")
    after_lines.extend(_wrap_list(kw.get("all"), col_width - 2))

    header = (
        f"doc_id: {doc_id}\n"
        f"title : {title}\n"
        f"chunks: {synthesis.chunk_count}\n"
    )
    table = _side_by_side(
        "BEFORE  (XML editorial tags)", before_lines,
        "AFTER   (Phase 1-4 enrichment)", after_lines,
        col_width=col_width,
    )
    return header + "\n" + table


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def _load_chunks(paths: Iterable[Path]) -> list[dict]:
    out: list[dict] = []
    for p in paths:
        data = json.loads(Path(p).read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError(f"{p}: expected a JSON list of chunks")
        out.extend(data)
    return out


def _load_parsed_index(paths: Iterable[Path]) -> dict[str, dict]:
    """Load one-or-more parsed_docs.json files; key by doc_id."""
    index: dict[str, dict] = {}
    for p in paths:
        data = json.loads(Path(p).read_text(encoding="utf-8"))
        if isinstance(data, list):
            iterable = data
        elif isinstance(data, dict) and isinstance(data.get("documents"), list):
            iterable = data["documents"]
        else:
            raise ValueError(f"{p}: unsupported parsed_docs.json shape")
        for d in iterable:
            did = d.get("doc_id")
            if did:
                index[did] = d
    return index


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 4 — roll chunk enrichment up to documents")
    ap.add_argument("--chunks", nargs="+", type=Path, required=True,
                    help="Enriched chunk JSON (with L1–L4 tags)")
    ap.add_argument("--parsed", nargs="+", type=Path, required=True,
                    help="parsed_docs.json files produced by src.rag_parser")
    ap.add_argument("--out",    type=Path,
                    default=Path("data/phase4/final_enriched_documents.json"))
    ap.add_argument("--compare", default=None,
                    help="Print Before/After comparison for this doc_id "
                         "(no synthesis output is suppressed; the comparison "
                         "is printed in addition to the file write)")
    ap.add_argument("--col-width", type=int, default=48,
                    help="Column width for --compare (reduce for narrow terminals)")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    chunks = _load_chunks(args.chunks)
    parsed_index = _load_parsed_index(args.parsed)
    print(f"Loaded {len(chunks)} chunks from {len(args.chunks)} file(s).")
    print(f"Loaded {len(parsed_index)} parsed documents from {len(args.parsed)} file(s).")

    synths = synthesize_corpus(chunks, parsed_docs_index=parsed_index)
    print(f"Synthesized {len(synths)} document(s).")

    # --- Summary log ---
    for s in synths:
        tax = s.taxonomy
        primary = ", ".join(p["l2_topic"] for p in tax.get("L2_Primary_Topics") or [])
        print(f"  {s.doc_id:<40}  L1={tax.get('L1_Domain')!r:<28}  "
              f"chunks={s.chunk_count:>3}  primary L2: {primary}")

    # --- Compare visualization ---
    if args.compare:
        target = next((s for s in synths if s.doc_id == args.compare), None)
        if target is None:
            print(f"\n[error] --compare {args.compare!r} not found; "
                  f"available: {[s.doc_id for s in synths]}", file=sys.stderr)
            return 2
        parsed_doc = parsed_index.get(args.compare) or {}
        print()
        print(render_compare(args.compare, target, parsed_doc, col_width=args.col_width))

    # --- Write output ---
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps([s.to_dict() for s in synths], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
