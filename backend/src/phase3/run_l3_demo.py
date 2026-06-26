"""
Phase 3.3 L3 sub-topic discovery demo.

Reads routed chunks (post Phase 3.1), picks one populated L2 group, clusters
them via Cluster-then-Label, and calls the namer to label each cluster.

If the input chunks don't yet have L2_Topic (i.e. they came straight from
the chunker), the CLI can route them on the fly with --auto-route.

Usage (typical):
  python -m src.phase3.run_l3_demo \\
      --chunks data/phase3/routed_gemini_sample.json \\
      --master data/rag_out/master_dictionary.json \\
      --out    data/phase3/l3_sample.json \\
      --namer  google
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from .l3_discovery import (
    DEFAULT_DISTANCE_THRESHOLD,
    DEFAULT_MIN_CLUSTER_SIZE,
    discover_l3_for_l2,
    group_by_l2,
)
from .providers import make_embedder, make_generator, make_namer
from .router import TopicRouter


def _load_chunks(paths: list[Path]) -> list[dict]:
    out: list[dict] = []
    for p in paths:
        out.extend(json.loads(p.read_text(encoding="utf-8")))
    return out


def _maybe_auto_route(chunks: list[dict], master: dict, args) -> list[dict]:
    """If chunks lack L2_Topic, run the Phase 3.1 router over them first.

    This keeps the demo self-contained for users who feed in raw
    chunked_docs.json rather than a previously-routed file.
    """
    unrouted = [c for c in chunks if not c.get("L2_Topic")]
    if not unrouted:
        return chunks
    if not args.auto_route:
        print(f"[info] {len(unrouted)}/{len(chunks)} chunks have no L2_Topic; "
              f"pass --auto-route to route them first.", file=sys.stderr)
        return [c for c in chunks if c.get("L2_Topic")]

    print(f"[auto-route] routing {len(unrouted)} chunks via Phase 3.1 "
          f"(embedder={args.embedder}, generator={args.generator})")
    embedder = make_embedder(args.embedder)
    generator = make_generator(args.generator)
    router = TopicRouter(master, embedder, generator)
    routed: list[dict] = []
    # Keep already-routed chunks untouched.
    for c in chunks:
        if c.get("L2_Topic"):
            routed.append(c)
            continue
        for r in router.route(c):
            routed.append(r.chunk)
    return routed


def _pick_l2_group(groups: dict[str, list[dict]], requested: str | None,
                   min_members: int) -> tuple[str, list[dict]]:
    """Pick either the requested L2 or the most-populated one meeting
    min_members. Dies with a readable error if no L2 qualifies."""
    if requested:
        if requested not in groups:
            raise SystemExit(
                f"--l2 {requested!r} not found. Available L2 topics: "
                f"{sorted(groups.keys())}"
            )
        return requested, groups[requested]

    # Default: largest populated group.
    candidates = sorted(
        ((k, v) for k, v in groups.items() if len(v) >= min_members),
        key=lambda kv: -len(kv[1]),
    )
    if not candidates:
        raise SystemExit(
            f"No L2 group has >= {min_members} members. "
            f"Inspect groups: "
            f"{ {k: len(v) for k, v in groups.items()} }"
        )
    return candidates[0]


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 3.3 L3 sub-topic discovery demo")
    ap.add_argument("--chunks", nargs="+", type=Path, required=True)
    ap.add_argument("--master", type=Path, required=True)
    ap.add_argument("--out",    type=Path, default=Path("data/phase3/l3_sample.json"))
    ap.add_argument("--l2",     default=None,
                    help="Target L2_Topic (default: largest populated group)")
    ap.add_argument("--sample", type=int, default=0,
                    help="Optional cap on chunks to process (0 = all routed)")
    ap.add_argument("--seed",   type=int, default=7)

    ap.add_argument("--embedder",  default="gemini",
                    choices=["gemini", "sentence-transformers", "st", "dummy"])
    ap.add_argument("--namer",     default="google",
                    choices=["google", "vertex", "dummy"])
    # For auto-route (chunks that have not yet been through 3.1).
    ap.add_argument("--auto-route", action="store_true",
                    help="If chunks lack L2_Topic, run Phase 3.1 router first")
    ap.add_argument("--generator", default="google",
                    choices=["google", "vertex", "dummy"],
                    help="Used only when --auto-route is set")

    ap.add_argument("--distance-threshold", type=float,
                    default=DEFAULT_DISTANCE_THRESHOLD)
    ap.add_argument("--min-cluster-size",   type=int,
                    default=DEFAULT_MIN_CLUSTER_SIZE)
    ap.add_argument("--min-group-size",     type=int, default=3,
                    help="Minimum chunks an L2 must have to be picked "
                         "when --l2 is not specified")
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    chunks = _load_chunks(args.chunks)
    master = json.loads(args.master.read_text(encoding="utf-8"))
    print(f"Loaded {len(chunks)} chunks from {len(args.chunks)} file(s).")

    chunks = _maybe_auto_route(chunks, master, args)
    print(f"Chunks with L2_Topic after routing: {len(chunks)}")

    if args.sample and args.sample < len(chunks):
        random.Random(args.seed).shuffle(chunks)
        chunks = chunks[:args.sample]
        print(f"[sampling] capped to {len(chunks)} chunks (seed={args.seed})")

    # Group and pick L2.
    groups = group_by_l2(chunks)
    print(f"L2 group populations: "
          f"{ {k: len(v) for k, v in sorted(groups.items(), key=lambda kv: -len(kv[1]))} }")
    l2_topic, l2_chunks = _pick_l2_group(groups, args.l2, args.min_group_size)
    print(f"\nSelected L2: {l2_topic!r}  ({len(l2_chunks)} chunks)")

    # Build providers.
    embedder = make_embedder(args.embedder)
    namer    = make_namer(args.namer)
    print(f"Embedder:  {args.embedder} ({embedder.__class__.__name__})")
    print(f"Namer:     {args.namer} ({namer.__class__.__name__})")

    labelled, audits = discover_l3_for_l2(
        l2_chunks, l2_topic, embedder, namer,
        distance_threshold=args.distance_threshold,
        min_cluster_size=args.min_cluster_size,
    )

    real_clusters = [a for a in audits if a.cluster_id != -1]
    noise         = [a for a in audits if a.cluster_id == -1]
    print(f"\n=== Clustering result ===")
    print(f"  real clusters: {len(real_clusters)}")
    print(f"  noise buckets: {len(noise)}")
    print()

    for a in audits:
        tag = "NOISE" if a.cluster_id == -1 else f"CLUSTER {a.cluster_id}"
        print(f"--- {tag}  size={a.size}  L3='{a.l3_sub_topic}'")
        if a.cluster_id != -1:
            print(f"    members:  {a.member_chunk_ids[:6]}"
                  f"{'...' if len(a.member_chunk_ids) > 6 else ''}")
            print(f"    centroids (shipped to namer): {a.centroid_chunk_ids}")
            print(f"    justification: {a.justification}")
            preview = (a.centroid_text_preview or '').replace('\n', ' ')
            print(f"    centroid-text preview (first 200ch): {preview[:200]}")
        else:
            print(f"    members: {a.member_chunk_ids}")
        print()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(labelled, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"Wrote {len(labelled)} L3-labelled chunks -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
