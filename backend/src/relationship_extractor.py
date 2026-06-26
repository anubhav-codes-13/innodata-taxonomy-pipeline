"""
Phase 2.2 — Relationship graph extractor.

Reads one or more `parsed_docs.json` files (produced by `src.rag_parser`) and
emits a flat list of directed graph edges to `relationship_graph.json`.

Each document's `edges.xrefs` list supplies the raw cross-references; this
script:

  1. Sets the source node to the document's doc_id.
  2. Normalises the target. For internal KLI references the target is the
     target document id (e.g. "KLI-KCL-Roy-2024-Ch01"). For URL / mailto
     references the target is the URL string itself.
  3. Classifies each edge as internal or external:
       - external: target starts with mailto: / http:// / https:// / ftp://
       - internal: everything else (including bare KLI-… ids, section
         anchors like "S0002", and PDF companion refs like
         "KLI-KCL-0949015.pdf")
  4. Filters the output to internal edges only by default; `--include-external`
     keeps them flagged so the caller can triage.
  5. Resolves the `target_id` against the set of known doc_ids across ALL
     input files — this is tracked in the optional `target_resolved` flag
     but the primary output matches the spec shape exactly.
  6. Omits edges whose source doc has no id (shouldn't happen, but defend).
  7. Deduplicates identical (source, target, type) triples — same edge
     repeated in multiple footnotes shouldn't inflate the graph.

Output (relationship_graph.json): list of edge dicts shaped as
  {
    "source_doc_id": "...",
    "target_id":     "...",
    "edge_type":     "ref|sec|toc|url|...",  # preserved from source
    "context_text":  "..."                    # may be null
  }

Usage:
    python -m src.relationship_extractor <parsed_docs.json> [<more>...] \\
        [--out relationship_graph.json] [--include-external] [--keep-duplicates]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


# External schemes we treat as "not part of the repository graph" unless
# --include-external is passed. mailto: is explicitly listed because it's
# common in author bio footnotes and would otherwise look like an internal
# bare id.
_EXTERNAL_PREFIXES: tuple[str, ...] = (
    "mailto:", "http://", "https://", "ftp://", "tel:", "file://",
)


def _is_external(target: str, edge_type: str | None) -> bool:
    """Treat as external if the URL scheme is explicit OR the xref is
    marked type="url" (some URLs in the source lack an http:// scheme
    but are still plainly web links — e.g. "sk.ua/...")."""
    if (edge_type or "").lower() == "url":
        return True
    return target.lower().startswith(_EXTERNAL_PREFIXES)


def _load_docs(paths: list[Path]) -> list[dict]:
    """Concatenate parsed_docs.json files. Same shape tolerance as tag_harvester."""
    all_docs: list[dict] = []
    for p in paths:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list):
            all_docs.extend(data)
        elif isinstance(data, dict) and isinstance(data.get("documents"), list):
            all_docs.extend(data["documents"])
        else:
            raise ValueError(f"{p}: unsupported shape")
    return all_docs


# Section anchors inside the same doc look like "S0001", "a00023", etc. —
# a short alphanumeric starting with a letter and containing no dots or
# slashes. They aren't document ids, so we don't count them as resolvable
# inter-document edges.
_SECTION_ANCHOR_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,15}$")


def _looks_like_doc_id(target: str) -> bool:
    """Heuristic: does this target string look like a KLI document id?"""
    # Strip any anchor fragment ("KLI-KCL-Roy-2024-Ch01#S0002")
    core = target.split("#", 1)[0]
    # KLI- prefix or ipn/number-style ids (e.g. "ipn26250") both qualify.
    return core.startswith("KLI-") or (core.lower().startswith("ipn") and core[3:].isdigit())


def build_graph(
    docs: list[dict],
    include_external: bool = False,
    keep_duplicates: bool = False,
) -> tuple[list[dict], dict]:
    """Return (edges_list, summary_stats).

    summary_stats is used by the CLI for the per-run report and by callers
    that want telemetry without re-walking the output.
    """
    known_ids: set[str] = {d["doc_id"] for d in docs if d.get("doc_id")}

    edges: list[dict] = []
    seen: set[tuple[str | None, str, str | None]] = set()
    stats = {
        "total_xrefs_seen":   0,
        "source_id_missing":  0,
        "target_empty":       0,
        "external_seen":      0,
        "external_kept":      0,
        "duplicates_dropped": 0,
        "edges_emitted":      0,
        "resolved_internal":  0,
    }

    for doc in docs:
        source = doc.get("doc_id")
        xrefs = ((doc.get("edges") or {}).get("xrefs")) or []
        for x in xrefs:
            stats["total_xrefs_seen"] += 1
            target = (x.get("target") or "").strip()
            if not target:
                stats["target_empty"] += 1
                continue
            if not source:
                stats["source_id_missing"] += 1
                continue

            edge_type = x.get("type") or None
            context   = x.get("text") or None

            ext = _is_external(target, edge_type)
            if ext:
                stats["external_seen"] += 1
                if not include_external:
                    continue
                stats["external_kept"] += 1

            if not keep_duplicates:
                key = (source, target, edge_type)
                if key in seen:
                    stats["duplicates_dropped"] += 1
                    continue
                seen.add(key)

            if not ext and _looks_like_doc_id(target) and target.split("#", 1)[0] in known_ids:
                stats["resolved_internal"] += 1

            edges.append({
                "source_doc_id": source,
                "target_id":     target,
                "edge_type":     edge_type,
                "context_text":  context,
            })
            stats["edges_emitted"] += 1

    return edges, stats


def main() -> int:
    ap = argparse.ArgumentParser(description="Build relationship_graph.json from parsed_docs.json")
    ap.add_argument("parsed_jsons", nargs="+", type=Path,
                    help="One or more parsed_docs.json files to merge")
    ap.add_argument("--out", type=Path, default=Path("relationship_graph.json"),
                    help="Output path (default: relationship_graph.json in CWD)")
    ap.add_argument("--include-external", action="store_true",
                    help="Keep mailto:/http:/https: edges in the output "
                         "(default: filtered out)")
    ap.add_argument("--keep-duplicates", action="store_true",
                    help="Keep identical (source, target, type) triples "
                         "(default: deduplicated)")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    for p in args.parsed_jsons:
        if not p.is_file():
            print(f"[error] {p} not found", file=sys.stderr)
            return 2

    docs = _load_docs(args.parsed_jsons)
    edges, stats = build_graph(docs,
                               include_external=args.include_external,
                               keep_duplicates=args.keep_duplicates)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(edges, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    print(f"Loaded {len(docs)} documents from {len(args.parsed_jsons)} file(s)")
    print(f"Wrote  {len(edges)} edges -> {args.out}")
    for k, v in stats.items():
        print(f"  {k:<22}  {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
