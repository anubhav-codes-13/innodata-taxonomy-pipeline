"""
POC full-corpus driver: route + L4 one document at a time, with checkpointing.

For each document:
  1. Pull its chunks from the combined chunk files.
  2. Route them through Phase 3.1 (L1 + L2 anchor/expand).
  3. Extract L4 entities + keywords.
  4. Retry any failed L4 chunks once (Gemini occasionally returns an
     unparseable response on the first try).
  5. Write the enriched chunks to data/<out>/per_doc/<doc_id>_enriched.json.

Resume behaviour: a doc whose *_enriched.json file already exists is
skipped. Delete the file to force a re-run for that doc.

Failure handling:
  * Transient 429 / 503: the provider-level backoff retries 4 times.
  * Persistent L4 error on one chunk: record `L4_metadata=null` for that
    chunk and carry on; the doc isn't aborted.
  * Anything uncaught at the doc level is logged and the loop continues
    to the next doc.

Intended use:
  python -m src.phase3.run_full_poc \\
      --chunks data/poc_output/ka_chunks.json data/poc_output/kcl_chunks.json \\
      --master data/poc_output/master_dictionary.json \\
      --per-doc-dir data/poc_output/per_doc
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .l4_extractor import L4ExtractionNode
from .providers import make_embedder, make_extractor, make_generator
from .router import TopicRouter


def _load_chunks(paths: list[Path]) -> list[dict]:
    out: list[dict] = []
    for p in paths:
        out.extend(json.loads(p.read_text(encoding="utf-8")))
    return out


def _group_by_doc(chunks: list[dict]) -> dict[str, list[dict]]:
    """Preserve input order within each doc; sort doc_ids alphabetically
    for a deterministic processing order."""
    by_doc: dict[str, list[dict]] = {}
    for c in chunks:
        doc_id = c.get("doc_id")
        if doc_id:
            by_doc.setdefault(doc_id, []).append(c)
    return dict(sorted(by_doc.items()))


def process_document(doc_id: str,
                     doc_chunks: list[dict],
                     router: TopicRouter,
                     l4_node: L4ExtractionNode,
                     retry_failed_l4_once: bool = True) -> tuple[list[dict], dict]:
    """Run Phase 3.1 + 3.2 on one document's chunks.

    Returns (enriched_chunks, stats_dict).
    """
    stats = {"routed": 0, "anchored": 0, "expanded": 0, "skipped": 0,
             "l4_ok": 0, "l4_err": 0}

    # ---- Phase 3.1: route ----
    # For a single doc, all chunks belong to the same L1 path (cust_groups
    # are doc-level). Each route() call yields 1..N RouterResults — we
    # take the first result as the enriched chunk for each input chunk.
    routed: list[dict] = []
    for c in doc_chunks:
        results = router.route(c)
        if not results:
            routed.append(c)
            stats["skipped"] += 1
            continue
        # Multi-L1 docs are rare; when they exist, pick the first result.
        r = results[0]
        routed.append(r.chunk)
        stats["routed"] += 1
        if r.decision == "ANCHORED":
            stats["anchored"] += 1
        elif r.decision == "EXPANDED":
            stats["expanded"] += 1
        else:
            stats["skipped"] += 1

    # ---- Phase 3.2: L4 ----
    enriched: list[dict] = []
    needs_retry: list[int] = []
    for i, c in enumerate(routed):
        r = l4_node.extract(c)
        enriched.append(r.chunk)
        if r.status == "EXTRACTED":
            stats["l4_ok"] += 1
        else:
            needs_retry.append(i)

    # One retry pass for transient failures (common with Gemini 429/parse).
    if retry_failed_l4_once and needs_retry:
        for i in needs_retry:
            r = l4_node.extract(enriched[i])
            if r.status == "EXTRACTED":
                enriched[i] = r.chunk
                stats["l4_ok"] += 1
            else:
                stats["l4_err"] += 1
    else:
        stats["l4_err"] += len(needs_retry)

    return enriched, stats


def main() -> int:
    ap = argparse.ArgumentParser(description="Full-corpus POC runner: route+L4 per doc with checkpointing")
    ap.add_argument("--chunks", nargs="+", type=Path, required=True)
    ap.add_argument("--master", type=Path, required=True)
    ap.add_argument("--per-doc-dir", type=Path, required=True)
    ap.add_argument("--embedder", default="gemini",
                    choices=["gemini", "sentence-transformers", "st", "dummy"])
    ap.add_argument("--generator", default="google",
                    choices=["google", "vertex", "dummy"])
    ap.add_argument("--extractor", default="google",
                    choices=["google", "vertex", "dummy"])
    ap.add_argument("--limit", type=int, default=0,
                    help="Stop after this many NEW docs (0 = all). Useful for "
                         "partial runs / quota conservation.")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    args.per_doc_dir.mkdir(parents=True, exist_ok=True)

    chunks = _load_chunks(args.chunks)
    master = json.loads(args.master.read_text(encoding="utf-8"))
    by_doc = _group_by_doc(chunks)
    total_docs = len(by_doc)
    total_chunks = sum(len(v) for v in by_doc.values())

    embedder  = make_embedder(args.embedder)
    generator = make_generator(args.generator)
    extractor = make_extractor(args.extractor)
    router = TopicRouter(master, embedder, generator)  # auto-threshold
    l4_node = L4ExtractionNode(master, extractor)

    print(f"docs: {total_docs}  chunks: {total_chunks}")
    print(f"embedder: {args.embedder}  generator: {args.generator}  extractor: {args.extractor}")
    print(f"per-doc dir: {args.per_doc_dir}")
    print()

    processed = 0
    skipped_resume = 0
    failed_docs: list[tuple[str, str]] = []
    run_start = time.time()

    for idx, (doc_id, doc_chunks) in enumerate(by_doc.items(), start=1):
        out_path = args.per_doc_dir / f"{doc_id}_enriched.json"
        if out_path.is_file():
            skipped_resume += 1
            # Still log so the user sees progress counters align.
            print(f"[{idx}/{total_docs}] {doc_id:<40}  SKIP (exists)")
            continue

        if args.limit and processed >= args.limit:
            print(f"\n[limit] stopping after {processed} new docs")
            break

        t0 = time.time()
        try:
            enriched, stats = process_document(doc_id, doc_chunks, router, l4_node)
        except Exception as exc:
            failed_docs.append((doc_id, repr(exc)))
            print(f"[{idx}/{total_docs}] {doc_id:<40}  FAIL {exc!r}", file=sys.stderr)
            continue

        out_path.write_text(json.dumps(enriched, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        dt = time.time() - t0
        processed += 1
        print(f"[{idx}/{total_docs}] {doc_id:<40}  "
              f"{len(doc_chunks):>3} chunks  "
              f"route(A{stats['anchored']}/E{stats['expanded']})  "
              f"L4 {stats['l4_ok']}/{stats['l4_ok']+stats['l4_err']}  "
              f"{dt:>5.1f}s")

    total_dt = time.time() - run_start
    print(f"\nprocessed {processed} new, skipped {skipped_resume} resumed, "
          f"failed {len(failed_docs)} in {total_dt/60:.1f} min")
    if failed_docs:
        print("failed docs:")
        for doc_id, err in failed_docs:
            print(f"  {doc_id}: {err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
