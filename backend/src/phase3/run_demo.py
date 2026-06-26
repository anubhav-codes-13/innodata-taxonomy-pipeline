"""
Phase 3.1 demo runner.

Picks a deterministic sample of chunks from chunked_docs.json, runs them
through the TopicRouter against master_dictionary.json, and prints the
"ANCHORED" / "EXPANDED" log required by the spec.

Default providers:
  embedder  = DummyEmbedder         (hashing-based, zero dependencies)
  generator = DummyGenerator        (offline placeholder for Gemini)

Swap to production providers via flags:
  --embedder sentence-transformers --embedder-model BAAI/bge-small-en-v1.5
  --generator google    (needs GOOGLE_API_KEY)
  --generator vertex    (needs GOOGLE_CLOUD_PROJECT and ADC)

Usage:
  python -m src.phase3.run_demo \\
      --chunks data/rag_out/ka_chunks.json data/rag_out/kcl_chunks.json \\
      --master data/rag_out/master_dictionary.json \\
      --sample 10 --out data/phase3/routed_sample.json
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from .providers import make_embedder, make_generator
from .router import TopicRouter, ANCHOR_SIM_THRESHOLD


def _load_chunks(paths: list[Path]) -> list[dict]:
    all_chunks: list[dict] = []
    for p in paths:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError(f"{p}: expected a JSON list of chunks")
        all_chunks.extend(data)
    return all_chunks


def _pick_sample(chunks: list[dict], n: int, seed: int) -> list[dict]:
    """Stratified-ish sample: try to include both KA and KCL if both exist.

    `n <= 0` or `n >= len(chunks)` means "use everything" (order preserved).
    """
    if n <= 0 or n >= len(chunks):
        return list(chunks)
    rng = random.Random(seed)
    ka  = [c for c in chunks if "KA"  in (c.get("cust_groups") or [])]
    kcl = [c for c in chunks if "KCL" in (c.get("cust_groups") or [])]
    out: list[dict] = []
    if ka and kcl:
        half = max(1, n // 2)
        out.extend(rng.sample(ka, min(half, len(ka))))
        remaining = max(0, n - len(out))
        out.extend(rng.sample(kcl, min(remaining, len(kcl))))
    else:
        pool = ka or kcl or chunks
        out = rng.sample(pool, min(n, len(pool)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Phase 3.1 router smoke-test")
    ap.add_argument("--chunks", nargs="+", type=Path, required=True,
                    help="One or more chunked_docs.json files")
    ap.add_argument("--master", type=Path, required=True,
                    help="Path to master_dictionary.json (domain-partitioned)")
    ap.add_argument("--sample", type=int, default=10,
                    help="Number of chunks to route")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--threshold", type=float, default=None,
                    help="Cosine anchor threshold. Defaults to the embedder's "
                         "calibrated value (bge-small=0.85, gemini=0.75, dummy=0.30).")
    ap.add_argument("--embedder",  default="gemini",
                    choices=["gemini", "sentence-transformers", "st", "dummy"])
    ap.add_argument("--embedder-model", default="BAAI/bge-small-en-v1.5")
    ap.add_argument("--generator", default="dummy",
                    choices=["dummy", "google", "vertex"])
    ap.add_argument("--gen-model", default=None,
                    help="Generator model name override (provider-specific)")
    ap.add_argument("--out", type=Path, default=Path("data/phase3/routed_sample.json"))
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    # Build provider objects.
    embedder_kwargs = {}
    if args.embedder in ("sentence-transformers", "st"):
        embedder_kwargs["model_name"] = args.embedder_model
    embedder = make_embedder(args.embedder, **embedder_kwargs)

    generator_kwargs = {}
    if args.gen_model and args.generator in ("google", "vertex"):
        generator_kwargs["model_name"] = args.gen_model
    generator = make_generator(args.generator, **generator_kwargs)

    # Report the effective model name when the generator has one — makes
    # it obvious whether we hit Gemini 2.5 Flash or fell back to a dummy.
    gen_model = getattr(generator, "model_name", None)
    gen_label = f"{generator.__class__.__name__}"
    if gen_model:
        gen_label += f" (model={gen_model})"

    # Router derives the effective threshold from the embedder when
    # --threshold is omitted; mirror that logic here for the banner.
    from .router import _auto_threshold
    effective_threshold = (
        float(args.threshold) if args.threshold is not None
        else _auto_threshold(embedder)
    )
    threshold_note = "auto" if args.threshold is None else "override"

    print(f"Embedder:  {args.embedder} ({embedder.__class__.__name__})")
    print(f"Generator: {args.generator} ({gen_label})")
    print(f"Threshold: {effective_threshold} ({threshold_note})")
    print()

    # Load data.
    chunks = _load_chunks(args.chunks)
    master = json.loads(args.master.read_text(encoding="utf-8"))
    print(f"Loaded {len(chunks)} chunks from {len(args.chunks)} file(s).")
    print(f"Master domains: {[k for k in master if k != 'global_entities']}")
    print()

    # Sample, route, log.
    sample = _pick_sample(chunks, args.sample, args.seed)
    print(f"Routing {len(sample)} chunks (seed={args.seed}):\n")

    router = TopicRouter(master, embedder, generator, anchor_threshold=args.threshold)
    routed: list[dict] = []
    anchored = expanded = skipped = errored = 0

    for c in sample:
        for r in router.route(c):
            sim_str = f"{r.similarity:.3f}" if r.similarity is not None else "  N/A"
            if r.decision == "ANCHORED":
                anchored += 1
                print(f"  [ANCHORED]  {r.chunk_id:<35}  L1={r.l1_domain:<25}  "
                      f"sim={sim_str}  L2={r.l2_topic}")
            elif r.decision == "EXPANDED":
                if r.l2_source == "generator_error":
                    errored += 1
                    err = (r.generator_info or {}).get("error", "unknown")
                    print(f"  [ERROR]     {r.chunk_id:<35}  L1={r.l1_domain:<25}  "
                          f"sim={sim_str}  err={err}")
                else:
                    expanded += 1
                    print(f"  [EXPANDED]  {r.chunk_id:<35}  L1={r.l1_domain:<25}  "
                          f"sim={sim_str}  L2={r.l2_topic!r}")
                    reasoning = (r.generator_info or {}).get("reasoning")
                    if reasoning:
                        print(f"              └─ reasoning: {reasoning}")
            else:
                skipped += 1
                print(f"  [SKIPPED]   {r.chunk_id:<35}  (no known cust_group)")
            routed.append(r.chunk)

    total = anchored + expanded + skipped + errored
    print(f"\nSummary: anchored={anchored}  expanded={expanded}  "
          f"skipped={skipped}  errored={errored}  total={total}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(routed, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"Wrote routed chunks -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
