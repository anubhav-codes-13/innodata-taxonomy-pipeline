"""
Phase 3.1 router: L1 domain assignment + L2 topic anchoring / expanding.

Sequential flow per chunk:

  1. L1 domain from cust_groups (KCL -> "Competition Law",
     KA -> "International Arbitration"). Non-exclusive: a chunk tagged
     both KA and KCL gets routed into both L1 paths.

  2. Embed the chunk's fused_text once (single vector reused across L1s).

  3. For each L1 path, load (and cache) the embedded L2 anchor set from
     master_dictionary[L1][topics].values(). Compute max cosine similarity.

       - score >= ANCHOR_SIM_THRESHOLD  -> ANCHORED: assign the matched
         L2 and return.
       - otherwise                       -> EXPANDED: call the TopicGenerator
         to propose a new L2. The caller can decide whether to promote the
         proposal into master_dictionary (not done here — Phase 3.1 is just
         the router; vocabulary evolution is Phase 3.x).

Design notes:
  * Anchor embeddings are cached per-L1 inside TopicRouter so batch runs
    don't re-embed the topic set.
  * The router mutates a *copy* of the chunk and returns it; the input
    chunk list is never modified in place (keeps the data flow functional,
    easier to test).
  * Logging is structured (per-chunk RouterResult) so a caller can produce
    tables / histograms / review queues without re-parsing stdout.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Iterable

import numpy as np

from .providers import Embedder, TopicGenerator


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ANCHOR_SIM_THRESHOLD: float = 0.85  # legacy default (bge-small calibration)

# Fallback when the embedder doesn't advertise a recommended threshold
# (e.g. a third-party class). Uses the legacy 0.85 value as the safe
# conservative default — over-restrictive rather than over-permissive.
_DEFAULT_FALLBACK_THRESHOLD: float = ANCHOR_SIM_THRESHOLD


def _auto_threshold(embedder) -> float:
    """Return the embedder's recommended_anchor_threshold if present.

    Each concrete Embedder class in providers.py advertises a cosine
    threshold calibrated for its own similarity distribution (0.85 for
    bge-small, 0.75 for gemini-embedding-001, 0.30 for the hashing
    dummy). This makes the router self-aware of its embedding model
    and removes the magic-number problem.
    """
    value = getattr(embedder, "recommended_anchor_threshold", None)
    if value is None:
        return _DEFAULT_FALLBACK_THRESHOLD
    return float(value)


# cust_group → human-readable L1 domain label, per spec.
L1_DOMAIN_BY_CUSTGROUP: dict[str, str] = {
    "KA":  "International Arbitration",
    "KCL": "Competition Law",
    # Extend here as new product lines come online (e.g. "KIPL": "IP Law").
}

# Max characters of fused_text sent to the TopicGenerator. Keeps API cost
# and latency bounded when we hit a very long chunk. Cosine anchoring uses
# the full text — only the LLM call is truncated.
_MAX_GENERATOR_CHARS: int = 4000


# ---------------------------------------------------------------------------
# Router result record
# ---------------------------------------------------------------------------

@dataclass
class RouterResult:
    """Per-chunk audit record. `chunk` is the mutated chunk dict."""
    chunk_id:       str
    decision:       str              # "ANCHORED" | "EXPANDED" | "SKIPPED"
    l1_domain:      str | None
    l2_topic:       str | None
    l2_source:      str              # "anchor" | "generator" | "none"
    similarity:     float | None
    matched_l2:     str | None       # the anchor we matched (Anchored only)
    generator_info: dict | None
    chunk:          dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# L1 domain assignment
# ---------------------------------------------------------------------------

def assign_l1_domains(cust_groups: Iterable[str]) -> list[str]:
    """Return the list of L1 domain labels for a chunk's cust_groups.

    Order preserved from the cust_groups iterable so routing is deterministic.
    Unknown cust_groups (like secondary CH/IHB clusters) are silently ignored
    — they are not domains, just product tags.
    """
    out: list[str] = []
    seen: set[str] = set()
    for cg in cust_groups:
        label = L1_DOMAIN_BY_CUSTGROUP.get(cg)
        if label and label not in seen:
            out.append(label)
            seen.add(label)
    return out


# ---------------------------------------------------------------------------
# Stateful router (caches L2 anchor embeddings per L1)
# ---------------------------------------------------------------------------

class TopicRouter:
    """Routes chunks to L1 domains and anchors / expands L2 topics.

    The master_dictionary argument is the output of src.tag_harvester —
    specifically the domain-partitioned shape:
        {"KA": {"topics": {id: text}, ...}, "KCL": {...}, ...}

    We key the anchor cache by L1 domain label (not cust_group) so multi-
    cust_group inputs like ["KA","CH"] still share one KA cache.
    """

    def __init__(
        self,
        master_dictionary: dict,
        embedder: Embedder,
        generator: TopicGenerator,
        anchor_threshold: float | None = None,
    ) -> None:
        self.master_dictionary = master_dictionary
        self.embedder = embedder
        self.generator = generator
        # Auto-pick the threshold from the embedder class when the caller
        # doesn't specify one. This is the "pipeline self-aware of its
        # embedding model" fix — no more hardcoded 0.85 magic number.
        self.anchor_threshold = (
            float(anchor_threshold) if anchor_threshold is not None
            else _auto_threshold(embedder)
        )

        # Map cust_group -> L1 domain via the module table; then map L1
        # domain label back to the dictionary key for that domain. For the
        # current data both sides are cust_group ("KA" / "KCL") so the
        # reverse map is trivial.
        self._l1_to_dict_key: dict[str, str] = {
            label: cg for cg, label in L1_DOMAIN_BY_CUSTGROUP.items()
        }

        # Per-L1-domain-label cache of (topic_texts, embedded_matrix).
        self._anchor_cache: dict[str, tuple[list[str], np.ndarray]] = {}

    # ---- public API ------------------------------------------------------

    def route(self, chunk: dict) -> list[RouterResult]:
        """Route one chunk. Returns one RouterResult per matched L1 domain.

        A chunk in both KA and KCL cust_groups yields two results. The
        caller chooses how to merge (union topics, prefer first, etc.).
        Most chunks yield exactly one result.
        """
        l1_domains = assign_l1_domains(chunk.get("cust_groups") or [])
        if not l1_domains:
            return [RouterResult(
                chunk_id=chunk.get("chunk_id", "?"),
                decision="SKIPPED",
                l1_domain=None, l2_topic=None,
                l2_source="none", similarity=None,
                matched_l2=None, generator_info=None,
                chunk=copy.deepcopy(chunk),
            )]

        text = chunk.get("fused_text") or ""
        chunk_vec = self.embedder.embed([text])[0]  # (d,)

        results: list[RouterResult] = []
        for l1 in l1_domains:
            anchors_text, anchors_vecs = self._anchors_for(l1)

            best_idx, best_sim = -1, -1.0
            if anchors_vecs.size:
                # Both sides are L2-normalised so dot = cosine.
                sims = anchors_vecs @ chunk_vec
                best_idx = int(np.argmax(sims))
                best_sim = float(sims[best_idx])

            if best_sim >= self.anchor_threshold and best_idx >= 0:
                matched = anchors_text[best_idx]
                mutated = copy.deepcopy(chunk)
                mutated["L1_Domain"] = l1
                mutated["L2_Topic"] = matched
                mutated["L2_Source"] = "anchor"
                mutated["L2_Similarity"] = round(best_sim, 4)
                results.append(RouterResult(
                    chunk_id=chunk.get("chunk_id", "?"),
                    decision="ANCHORED",
                    l1_domain=l1, l2_topic=matched,
                    l2_source="anchor", similarity=best_sim,
                    matched_l2=matched, generator_info=None,
                    chunk=mutated,
                ))
                continue

            # Expand: call the generator.
            existing_l2s = anchors_text
            clipped_text = (text or "")[:_MAX_GENERATOR_CHARS]
            try:
                proposal = self.generator.propose_topic(
                    l1_domain=l1,
                    existing_l2s=existing_l2s,
                    text=clipped_text,
                )
            except Exception as exc:  # surface to caller via RouterResult
                mutated = copy.deepcopy(chunk)
                mutated["L1_Domain"] = l1
                mutated["L2_Topic"] = None
                mutated["L2_Source"] = "generator_error"
                mutated["L2_Similarity"] = round(best_sim, 4) if best_sim >= 0 else None
                results.append(RouterResult(
                    chunk_id=chunk.get("chunk_id", "?"),
                    decision="EXPANDED",
                    l1_domain=l1, l2_topic=None,
                    l2_source="generator_error",
                    similarity=best_sim if best_sim >= 0 else None,
                    matched_l2=None,
                    generator_info={"error": repr(exc)},
                    chunk=mutated,
                ))
                continue

            proposed = proposal.get("proposed_l2_topic")
            mutated = copy.deepcopy(chunk)
            mutated["L1_Domain"] = l1
            mutated["L2_Topic"] = proposed
            mutated["L2_Source"] = "generator"
            mutated["L2_Similarity"] = round(best_sim, 4) if best_sim >= 0 else None
            mutated["L2_Reasoning"] = proposal.get("reasoning")
            results.append(RouterResult(
                chunk_id=chunk.get("chunk_id", "?"),
                decision="EXPANDED",
                l1_domain=l1, l2_topic=proposed,
                l2_source="generator",
                similarity=best_sim if best_sim >= 0 else None,
                matched_l2=None,
                generator_info=proposal,
                chunk=mutated,
            ))

        return results

    # ---- internal --------------------------------------------------------

    def _anchors_for(self, l1_domain: str) -> tuple[list[str], np.ndarray]:
        """Return (texts, normalised_embeddings) for the L2 anchors in this L1.

        Missing domain -> empty arrays (router will always take the Expand
        path). Empty-topic domains behave the same.
        """
        if l1_domain in self._anchor_cache:
            return self._anchor_cache[l1_domain]

        dict_key = self._l1_to_dict_key.get(l1_domain)
        if not dict_key:
            self._anchor_cache[l1_domain] = ([], np.zeros((0, 0), dtype=np.float32))
            return self._anchor_cache[l1_domain]

        topics_map: dict[str, str] = (
            (self.master_dictionary.get(dict_key) or {}).get("topics") or {}
        )
        texts = [t for t in topics_map.values() if t and t.strip()]
        if not texts:
            self._anchor_cache[l1_domain] = ([], np.zeros((0, 0), dtype=np.float32))
            return self._anchor_cache[l1_domain]

        matrix = self.embedder.embed(texts)
        self._anchor_cache[l1_domain] = (texts, matrix)
        return self._anchor_cache[l1_domain]


# ---------------------------------------------------------------------------
# Functional convenience wrappers
# ---------------------------------------------------------------------------

def route_chunk(chunk: dict, master_dictionary: dict,
                embedder: Embedder, generator: TopicGenerator,
                anchor_threshold: float | None = None) -> list[RouterResult]:
    """One-shot router for callers who don't need the anchor cache.

    `anchor_threshold=None` (default) asks the embedder for its
    calibrated threshold.
    """
    return TopicRouter(master_dictionary, embedder, generator,
                       anchor_threshold).route(chunk)


def route_chunks(chunks: Iterable[dict], master_dictionary: dict,
                 embedder: Embedder, generator: TopicGenerator,
                 anchor_threshold: float | None = None) -> list[RouterResult]:
    """Batch wrapper that reuses a single TopicRouter (i.e. cached anchors).

    `anchor_threshold=None` (default) asks the embedder for its
    calibrated threshold.
    """
    router = TopicRouter(master_dictionary, embedder, generator, anchor_threshold)
    out: list[RouterResult] = []
    for c in chunks:
        out.extend(router.route(c))
    return out
