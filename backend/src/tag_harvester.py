"""
Tag harvester for the Wolters Kluwer RAG pipeline (Phase 2.1 — domain-partitioned).

Consolidates `enrichment.topics`, `enrichment.keywords`, `enrichment.countries`,
and `enrichment.organizations` from one or more `parsed_docs.json` files into
a single `master_dictionary.json`, PARTITIONED by primary legal domain.

Why partition? Arbitration (KA) and Competition Law (KCL) are substantively
different fields. Mixing their topic IDs and keywords in a flat list produces
retrieval/autosuggest noise ("Mergers" surfaced for an arbitration query,
"State Immunity" surfaced for a competition query). Partitioning by domain
gives retrieval a clean filter and lets the taxonomy evolve independently
per product line.

Domain = each value in `metadata.cust_groups`. A doc with `cust_groups =
["KA", "CH"]` contributes to the `KA` bucket; one with `["KA", "KCL"]` (rare
but not structurally prohibited) contributes to BOTH. Non-exclusive.

Entities (countries, organizations) stay GLOBAL — a country is a country
regardless of whether arbitration or competition law is discussing it.

Processing rules:

  Topics (ID-based taxonomy)
    - Accept either dict shape `{"id": "KCL-004", "text": "Liberalisation"}`
      or a bare string `"Investment Arbitration"` (legacy shape).
    - Canonical key = the explicit `id` when present.
    - When `id` is missing, synthesise one via slugification:
        "Investment Arbitration"  ->  KA-investment-arbitration
      The prefix is the domain the doc is being assigned to.
    - Conflicts (same id, different text across docs) are resolved first-wins
      with a stderr warning.

  Keywords (surface-level normalization)
    - Trim whitespace, collapse internal whitespace.
    - Drop decorative special characters BUT preserve meaningful ones:
      alphanumerics, spaces, hyphens, ampersands, slashes, periods — so
      legal citations like "Directive 2003/55/EC" and "R&D" survive.
    - Title-Case to resolve casing duplicates ("Arbitration" == "arbitration").
    - Deduplicated & sorted.

  Entities (countries + organizations, global)
    - rag_parser emits these as `{code, name}` dicts. Dedupe by code when
      available (ISO-2 country code or ORG-id is stable); fall back to
      name otherwise. Output a sorted list of display names.

Output (master_dictionary.json):
  {
    "KA":  { "topics": {id: text, ...}, "keywords": [...] },
    "KCL": { "topics": {id: text, ...}, "keywords": [...] },
    ...one block per domain discovered / requested...
    "global_entities": { "organizations": [...], "countries": [...] }
  }

Usage:
    # Default domains are KA + KCL.
    python -m src.tag_harvester <parsed_docs.json> [<parsed_docs.json> ...] \\
        [--out master_dictionary.json] [--domains KA KCL KIPL]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path


# ---------------------------------------------------------------------------
# Normalization primitives
# ---------------------------------------------------------------------------

# Keyword normalization: allow letters, digits, spaces, plus a small set of
# punctuation that carries meaning in legal terms (hyphen, slash, ampersand,
# period — periods survive here because they appear inside things like
# "U.S.". Trailing periods are stripped at the end.)
_KEYWORD_KEEP_RE = re.compile(r"[^\w\s\-/&.]+")

# Collapse runs of whitespace. Operates on already-normalised characters.
_WS_RE = re.compile(r"\s+")

# Slug: lowercase, non-alphanumerics -> '-', collapse and trim '-'.
_SLUG_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def normalize_keyword(raw: str) -> str | None:
    """Canonical form for a keyword string. Returns None if nothing useful remains."""
    if raw is None:
        return None
    text = str(raw)
    # Drop decorative chars while preserving meaningful punctuation.
    text = _KEYWORD_KEEP_RE.sub(" ", text)
    # Strip leading/trailing whitespace AND leading/trailing noise punctuation.
    text = _WS_RE.sub(" ", text).strip(" .-/&")
    if not text:
        return None
    # Title-case everything — resolves 'arbitration' vs 'Arbitration'.
    # .title() handles "state immunity" -> "State Immunity" correctly even
    # with internal punctuation, and is locale-insensitive (good here).
    return text.title()


def slugify(text: str) -> str:
    """'Investment Arbitration' -> 'investment-arbitration'."""
    if not text:
        return ""
    return _SLUG_NON_ALNUM_RE.sub("-", text.lower()).strip("-")


DEFAULT_DOMAINS: tuple[str, ...] = ("KA", "KCL")


def _doc_domains(doc: dict, known_domains: set[str]) -> list[str]:
    """Return every known domain listed in the doc's cust_groups.

    A doc with cust_groups=["KA","CH"] and known_domains={"KA","KCL"} yields
    ["KA"]. Secondary tags like CH/IHB are ignored (they're product clusters
    within a domain, not domains themselves). A doc contributing to multiple
    domains (e.g. ["KA","KCL"]) yields both — we do not force exclusivity.
    """
    cgs = (doc.get("metadata") or {}).get("cust_groups") or []
    return [c for c in cgs if c in known_domains]


# ---------------------------------------------------------------------------
# Harvesters — topics & keywords are domain-partitioned; entities are global.
# ---------------------------------------------------------------------------

def harvest_topics_by_domain(
    docs: list[dict], domains: tuple[str, ...]
) -> dict[str, dict[str, str]]:
    """Return {domain -> {topic_id -> canonical text}}.

    A topic observed in a doc that belongs to multiple known domains is
    recorded under each of those domains (e.g. an edge-case KA+KCL doc
    would populate both buckets). Topics from docs that belong to NO
    known domain are dropped with a stderr log — they need either a new
    --domain flag or a data fix.
    """
    known = set(domains)
    merged: dict[str, dict[str, str]] = {d: {} for d in domains}
    conflicts: dict[str, dict[str, set[str]]] = {d: defaultdict(set) for d in domains}
    orphaned = 0

    for doc in docs:
        doc_domains = _doc_domains(doc, known)
        topics = ((doc.get("enrichment") or {}).get("topics")) or []
        if not topics:
            continue
        if not doc_domains:
            orphaned += len(topics)
            continue

        for t in topics:
            tid: str | None = None
            text: str | None = None
            if isinstance(t, dict):
                tid = (t.get("id") or "").strip() or None
                text = (t.get("text") or "").strip() or None
            elif isinstance(t, str):
                text = t.strip() or None
            else:
                continue

            # Skip placeholders: empty id AND empty text.
            if not tid and not text:
                continue

            for domain in doc_domains:
                # Synthesise an id from the text when missing, prefixed with
                # the domain the topic is being assigned to.
                final_tid = tid
                if not final_tid:
                    slug = slugify(text or "")
                    if not slug:
                        continue
                    final_tid = f"{domain}-{slug}"

                bucket = merged[domain]
                if final_tid not in bucket:
                    bucket[final_tid] = text or ""
                elif text and bucket[final_tid] and text != bucket[final_tid]:
                    conflicts[domain][final_tid].update({bucket[final_tid], text})
                elif text and not bucket[final_tid]:
                    bucket[final_tid] = text

    if orphaned:
        print(f"[harvester] warning: {orphaned} topics from docs without any of "
              f"the known domains {sorted(known)} were skipped — add a "
              f"--domains flag if this is wrong", file=sys.stderr)

    for domain, dconf in conflicts.items():
        for tid, texts in dconf.items():
            print(f"[harvester] warning: topic id '{tid}' in domain "
                  f"'{domain}' has conflicting texts {sorted(texts)} — "
                  f"keeping '{merged[domain][tid]}'", file=sys.stderr)

    # Sorted IDs within each domain for stable output diffs.
    return {d: dict(sorted(merged[d].items())) for d in domains}


def harvest_keywords_by_domain(
    docs: list[dict], domains: tuple[str, ...]
) -> dict[str, list[str]]:
    """Return {domain -> sorted, deduplicated, normalized keywords}."""
    known = set(domains)
    buckets: dict[str, set[str]] = {d: set() for d in domains}
    orphaned = 0

    for doc in docs:
        doc_domains = _doc_domains(doc, known)
        kws = ((doc.get("enrichment") or {}).get("keywords")) or []
        if not kws:
            continue
        if not doc_domains:
            orphaned += len(kws)
            continue
        for kw in kws:
            norm = normalize_keyword(kw)
            if not norm:
                continue
            for domain in doc_domains:
                buckets[domain].add(norm)

    if orphaned:
        print(f"[harvester] warning: {orphaned} keywords from docs without "
              f"any of the known domains {sorted(known)} were skipped",
              file=sys.stderr)

    return {d: sorted(buckets[d]) for d in domains}


def _harvest_coded_entities(docs: list[dict], field: str) -> list[str]:
    """Shared dedupe logic for countries/organizations.

    Entries arrive as {code, name}; dedupe by code when present, else by
    name. The output list contains display names only — callers that need
    the codes should work off the raw parsed_docs.json.
    """
    by_code: dict[str, str] = {}     # code -> name (first non-empty)
    nameless_codes: set[str] = set() # codes with no name
    name_only: set[str] = set()      # name-only entries (no code)

    for doc in docs:
        entries = ((doc.get("enrichment") or {}).get(field)) or []
        for e in entries:
            if isinstance(e, dict):
                code = (e.get("code") or "").strip() or None
                name = (e.get("name") or "").strip() or None
            elif isinstance(e, str):
                code, name = None, e.strip() or None
            else:
                continue

            if not code and not name:
                continue
            if code:
                if name:
                    # Prefer the first non-empty name we see for a given code.
                    if code not in by_code or not by_code[code]:
                        by_code[code] = name
                else:
                    if code not in by_code:
                        nameless_codes.add(code)
            else:
                name_only.add(name)

    # Final display list: names from by_code, bare codes for any code that
    # never had an accompanying name, plus the name-only set.
    display: set[str] = set(v for v in by_code.values() if v)
    display.update(nameless_codes)
    display.update(name_only)
    return sorted(display)


def harvest_countries(docs: list[dict]) -> list[str]:
    return _harvest_coded_entities(docs, "countries")


def harvest_organizations(docs: list[dict]) -> list[str]:
    return _harvest_coded_entities(docs, "organizations")


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def load_parsed(path: Path) -> list[dict]:
    """Load a parsed_docs.json. Accepts either a top-level list OR a dict
    with a 'documents' key — both shapes exist in the wild after various
    export pipelines."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("documents"), list):
        return data["documents"]
    raise ValueError(f"{path}: unsupported shape; expected list of docs or {{documents: [...]}}")


def _load_seed_topics(path: Path) -> dict[str, dict[str, str]]:
    """Load a curated L2 taxonomy seed file.

    Shape:
      {
        "_comment": "...",           # ignored
        "KA":  { "topics": {id: text, ...} },
        "KCL": { "topics": {id: text, ...} }
      }
    Unknown domains are silently ignored; missing domains are fine.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, dict[str, str]] = {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected top-level object")
    for domain, block in data.items():
        if domain.startswith("_"):
            continue
        if not isinstance(block, dict):
            continue
        topics = block.get("topics") or {}
        if isinstance(topics, dict):
            out[domain] = {
                str(k).strip(): str(v).strip()
                for k, v in topics.items()
                if str(k).strip() and str(v).strip()
            }
    return out


def _merge_seed_topics(harvested: dict[str, dict[str, str]],
                       seeds: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
    """Merge seeds into harvested topics per domain.

    Policy:
      * Seed IDs win on ID collision (they are the canonical curated name).
      * Seed TEXT wins too (curated texts tend to be broader / cleaner).
      * Harvested topics that duplicate a seed by TEXT (case-insensitive)
        are dropped — e.g. if the harvester produced a synthetic id
        "KA-investment-arbitration" and the seed also has "Investment
        Arbitration" with id "KA-SEED-002", we keep the seed id.
      * Everything else from the harvested set is preserved.
    """
    merged: dict[str, dict[str, str]] = {}
    for domain, harvested_topics in harvested.items():
        seed_topics = seeds.get(domain, {})
        seed_texts_lc = {t.lower(): tid for tid, t in seed_topics.items()}

        combined: dict[str, str] = {}
        # Keep harvested entries first (so seeds overwrite them on id/text collision).
        for tid, text in harvested_topics.items():
            if tid in seed_topics:
                # Seed has this id — skip harvested, seed will add below.
                continue
            if (text or "").lower() in seed_texts_lc:
                # Seed already covers this topic by text — skip harvested duplicate.
                continue
            combined[tid] = text

        # Overlay seeds last so they win on collisions.
        for tid, text in seed_topics.items():
            combined[tid] = text

        # Stable ordering by id for deterministic output diffs.
        merged[domain] = dict(sorted(combined.items()))

    # Domains that exist in seeds but not in harvested get added as-is.
    for domain, seed_topics in seeds.items():
        if domain in merged:
            continue
        merged[domain] = dict(sorted(seed_topics.items()))
    return merged


def build_master_dictionary(docs: list[dict],
                            domains: tuple[str, ...] = DEFAULT_DOMAINS,
                            seed_topics: dict[str, dict[str, str]] | None = None,
                            drop_harvested_topics: bool = False,
                            ) -> dict:
    """Assemble the partitioned master dictionary.

    Per-domain: topics + keywords.
    Global: organizations + countries (universal entities, not domain-bound).

    `seed_topics`:
      - When provided (and drop_harvested_topics=False), seeds are merged
        into the harvested topics with seed IDs/texts winning on conflict.
      - When drop_harvested_topics=True, the harvested topic set is
        IGNORED and only seed topics are kept. Use this for "pristine
        taxonomy" runs where the seed dictionary is the absolute ground
        truth for the router — avoids near-duplicate anchors like
        "Mergers" (harvested) vs "Merger Control" (seed) competing for
        the same chunk. Keywords are unaffected (still harvested; seeds
        are topic-only by design).

    `drop_harvested_topics` is a no-op when `seed_topics` is None —
    dropping without replacing would leave every domain with an empty
    topics dictionary, which is almost always a mistake.
    """
    topics_by_domain: dict[str, dict[str, str]]
    if seed_topics and drop_harvested_topics:
        # Start from an empty harvested set so only seeds populate.
        topics_by_domain = {d: {} for d in domains}
        topics_by_domain = _merge_seed_topics(topics_by_domain, seed_topics)
    else:
        topics_by_domain = harvest_topics_by_domain(docs, domains)
        if seed_topics:
            topics_by_domain = _merge_seed_topics(topics_by_domain, seed_topics)

    keywords_by_domain = harvest_keywords_by_domain(docs, domains)

    out: dict = {}
    for domain in domains:
        out[domain] = {
            "topics":   topics_by_domain.get(domain, {}),
            "keywords": keywords_by_domain[domain],
        }
    out["global_entities"] = {
        "organizations": harvest_organizations(docs),
        "countries":     harvest_countries(docs),
    }
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Consolidate enrichment tags into master_dictionary.json")
    ap.add_argument("parsed_jsons", nargs="+", type=Path,
                    help="One or more parsed_docs.json files to merge")
    ap.add_argument("--out", type=Path, default=Path("master_dictionary.json"),
                    help="Output path (default: master_dictionary.json in CWD)")
    ap.add_argument("--domains", nargs="+", default=list(DEFAULT_DOMAINS),
                    help=f"cust_group values to treat as top-level domains "
                         f"(default: {' '.join(DEFAULT_DOMAINS)})")
    ap.add_argument("--seed-topics", type=Path, default=None,
                    help="Optional JSON file of canonical L2 topics to merge "
                         "into the harvested set. Seed IDs and texts win on "
                         "conflict. Shape: "
                         "{\"KA\": {\"topics\": {id: text}}, \"KCL\": {...}}. "
                         "Typical path: data/phase3/seed_topics.json")
    ap.add_argument("--drop-harvested-topics", action="store_true",
                    help="When a --seed-topics file is supplied, drop the "
                         "harvested topics entirely so only the curated "
                         "seed taxonomy is used. Produces a pristine "
                         "dictionary ideal for router ground-truth.")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    all_docs: list[dict] = []
    for path in args.parsed_jsons:
        if not path.is_file():
            print(f"[error] {path} not found", file=sys.stderr)
            return 2
        docs = load_parsed(path)
        all_docs.extend(docs)
        print(f"Loaded {len(docs):>4} docs from {path}")

    domains: tuple[str, ...] = tuple(args.domains)

    seed_topics: dict[str, dict[str, str]] | None = None
    if args.seed_topics:
        if not args.seed_topics.is_file():
            print(f"[error] --seed-topics file not found: {args.seed_topics}",
                  file=sys.stderr)
            return 2
        seed_topics = _load_seed_topics(args.seed_topics)
        total_seeds = sum(len(v) for v in seed_topics.values())
        print(f"Loaded {total_seeds} seed topics from {args.seed_topics}")

    if args.drop_harvested_topics and not seed_topics:
        print("[error] --drop-harvested-topics requires --seed-topics "
              "(dropping without replacing would leave topics empty)",
              file=sys.stderr)
        return 2
    if args.drop_harvested_topics:
        print("[pristine] harvested topics dropped; using seeds only")

    master = build_master_dictionary(all_docs, domains=domains,
                                     seed_topics=seed_topics,
                                     drop_harvested_topics=args.drop_harvested_topics)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(master, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    print(f"\nWrote {args.out}")
    for domain in domains:
        print(f"  {domain}: topics={len(master[domain]['topics'])}  "
              f"keywords={len(master[domain]['keywords'])}")
    ge = master["global_entities"]
    print(f"  global_entities: organizations={len(ge['organizations'])}  "
          f"countries={len(ge['countries'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
