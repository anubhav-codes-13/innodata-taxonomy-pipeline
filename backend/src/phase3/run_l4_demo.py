"""
Phase 3.2 L4 extraction demo runner.

Takes a set of chunks (typically Phase-3.1 routed output, but plain chunk
files work too — the L4 node resolves the domain key from cust_groups when
L1_Domain is absent), runs them through L4ExtractionNode, and logs the
extracted entities + keywords for each.

Usage:
  python -m src.phase3.run_l4_demo \\
      --chunks data/phase3/routed_gemini_sample.json \\
      --master data/rag_out/master_dictionary.json \\
      --out    data/phase3/l4_sample.json \\
      --extractor google
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from .l4_extractor import L4ExtractionNode
from .providers import make_extractor


def _load_chunks(paths: list[Path]) -> list[dict]:
    all_chunks: list[dict] = []
    for p in paths:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError(f"{p}: expected a JSON list of chunks")
        all_chunks.extend(data)
    return all_chunks


def _pick_sample(chunks: list[dict], n: int, seed: int) -> list[dict]:
    """Same stratified-ish sampling as the 3.1 demo so we get both KA+KCL."""
    rng = random.Random(seed)
    ka  = [c for c in chunks if "KA"  in (c.get("cust_groups") or [])]
    kcl = [c for c in chunks if "KCL" in (c.get("cust_groups") or [])]
    if n is None or n >= len(chunks):
        return chunks
    if ka and kcl:
        half = max(1, n // 2)
        out: list[dict] = []
        out.extend(rng.sample(ka, min(half, len(ka))))
        out.extend(rng.sample(kcl, min(n - len(out), len(kcl))))
        return out
    pool = ka or kcl or chunks
    return rng.sample(pool, min(n, len(pool)))


def _format_list(items: list[str], max_items: int = 5) -> str:
    if not items:
        return "(none)"
    trimmed = items[:max_items]
    tail = f" ... (+{len(items) - max_items} more)" if len(items) > max_items else ""
    return "; ".join(trimmed) + tail


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 3.2 L4 extractor smoke-test")
    ap.add_argument("--chunks", nargs="+", type=Path, required=True,
                    help="One or more chunk JSON files (routed or plain)")
    ap.add_argument("--master", type=Path, required=True,
                    help="master_dictionary.json (domain-partitioned)")
    ap.add_argument("--sample", type=int, default=6,
                    help="Number of chunks to run (0 = all)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--extractor", default="dummy",
                    choices=["dummy", "google", "vertex"])
    ap.add_argument("--ext-model", default=None,
                    help="Override extractor model name (google/vertex only)")
    ap.add_argument("--out", type=Path,
                    default=Path("data/phase3/l4_sample.json"))
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    extractor_kwargs = {}
    if args.ext_model and args.extractor in ("google", "vertex"):
        extractor_kwargs["model_name"] = args.ext_model
    extractor = make_extractor(args.extractor, **extractor_kwargs)

    ext_label = extractor.__class__.__name__
    ext_model = getattr(extractor, "model_name", None)
    if ext_model:
        ext_label += f" (model={ext_model})"

    print(f"Extractor: {args.extractor} ({ext_label})")
    print()

    chunks = _load_chunks(args.chunks)
    master = json.loads(args.master.read_text(encoding="utf-8"))
    print(f"Loaded {len(chunks)} chunks from {len(args.chunks)} file(s).")
    sample = chunks if args.sample == 0 else _pick_sample(chunks, args.sample, args.seed)
    print(f"Running L4 on {len(sample)} chunks (seed={args.seed}).\n")

    node = L4ExtractionNode(master, extractor)
    extracted: list[dict] = []
    stats = {"EXTRACTED": 0, "SKIPPED": 0, "ERROR": 0}

    for c in sample:
        r = node.extract(c)
        stats[r.status] = stats.get(r.status, 0) + 1
        domain = r.domain_key or "?"
        chunk_doc = c.get("doc_id", "?")
        print(f"--- {r.chunk_id}  (doc_id={chunk_doc}  domain={domain}  status={r.status})")
        if r.status == "ERROR":
            print(f"    error: {r.error}")
        elif r.status == "SKIPPED":
            print(f"    skipped: {r.error}")
        else:
            md = r.l4_metadata or {}
            ent = md.get("entities", {})
            kw = md.get("keywords", {})
            print(f"    case_names         : {_format_list(ent.get('case_names', []))}")
            print(f"    statutes           : {_format_list(ent.get('statutes_and_regulations', []))}")
            print(f"    organizations      : {_format_list(ent.get('organizations', []))}")
            print(f"    matched_keywords   : {_format_list(kw.get('existing_matched_keywords', []))}")
            print(f"    new_keywords       : {_format_list(kw.get('new_extracted_keywords', []))}")
        extracted.append(r.chunk)

    print(f"\nSummary: {stats}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(extracted, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"Wrote L4-enriched chunks -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
