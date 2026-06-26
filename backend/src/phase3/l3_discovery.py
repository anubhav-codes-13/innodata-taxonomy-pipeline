"""
Phase 3.3 — L3 sub-topic discovery via Cluster-then-Label.

Inputs:  a list of chunks that have already been routed by Phase 3.1
         (each has L1_Domain and L2_Topic). L4_metadata may or may not be
         present; this node does not depend on it.

Algorithm per L2 group:
  1. Collect chunks whose L2_Topic == the target L2.
  2. Embed their fused_text with the supplied Embedder.
  3. Run AgglomerativeClustering (cosine distance, distance-threshold
     mode) to discover clusters without having to pre-declare K. Small
     clusters (size < min_cluster_size) are merged into a synthetic
     "noise" bucket labelled -1 — this mirrors HDBSCAN's semantics while
     staying on sklearn (which is already a project dep).
  4. For each real cluster, pick the K chunks closest (cosine) to the
     cluster's mean vector. Concatenate their fused_text and ask the
     SubTopicNamer for a 2–4 word L3 name.
  5. Apply the L3 string to every chunk in the cluster. Noise chunks
     get "General {L2_Topic}".

Returns (chunks, clusters) where `chunks` is a shallow-copied list with
L3_Sub_Topic (+ provenance) applied, and `clusters` is a per-cluster audit
record listing members, centroid chunks, and the raw namer response.

Design notes:
  * We re-embed inside this module rather than reusing Phase 3.1's
    vectors because Phase 3.1 discards its vectors after the anchor/
    expand decision. Re-embedding ~hundreds of chunks on Gemini is cheap
    and keeps this script decoupled from router internals.
  * Clustering threshold is exposed as a CLI knob; default 0.35 cosine
    distance matches what bge-small/Gemini embeddings produce for
    "obviously same sub-topic" legal prose based on quick calibration
    on the sample corpora. Tune for the full corpus.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Iterable

import numpy as np

from .providers import Embedder, SubTopicNamer


# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

# Agglomerative threshold on cosine distance (1 - cosine_similarity).
# Smaller = tighter clusters (more clusters, smaller each).
DEFAULT_DISTANCE_THRESHOLD: float = 0.35

# A cluster smaller than this gets demoted to the noise bucket (-1).
# With only a few dozen chunks per L2 in the current sample, 2 is the
# minimum meaningful cluster; raise on larger corpora.
DEFAULT_MIN_CLUSTER_SIZE: int = 2

# Number of centroid chunks to send to the namer.
DEFAULT_CENTROIDS_K_MIN: int = 3
DEFAULT_CENTROIDS_K_MAX: int = 5

# Upper bound on how much of a centroid chunk we ship to Gemini. We join
# multiple centroids per call so per-chunk truncation keeps the total
# payload bounded. 2000 chars × 5 chunks ≈ 10k chars total — well under
# the model limit but small enough to keep cost/latency predictable.
_CENTROID_CHAR_CAP: int = 2000


# ---------------------------------------------------------------------------
# Audit records
# ---------------------------------------------------------------------------

@dataclass
class ClusterAudit:
    """Per-cluster record so callers can log / persist the decision."""
    cluster_id:       int                # -1 for noise
    l2_topic:         str
    size:             int
    member_chunk_ids: list[str]
    centroid_chunk_ids: list[str]
    centroid_text_preview: str           # first 200 chars for debug logs
    l3_sub_topic:     str
    justification:    str
    namer_raw:        dict | None = None # exact response (None for noise)


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------

def _cluster_labels(vecs: np.ndarray,
                    distance_threshold: float,
                    min_cluster_size: int) -> np.ndarray:
    """Return an int array of cluster ids (small clusters collapsed to -1).

    Edge case: when the sample has < 2 members, sklearn refuses to run;
    we skip clustering and return all-zero labels (treated as one group
    downstream, or noise if size < min_cluster_size).
    """
    n = vecs.shape[0]
    if n == 0:
        return np.zeros(0, dtype=np.int64)
    if n == 1:
        # Single-chunk "cluster"; caller will decide whether it's noise.
        return np.zeros(1, dtype=np.int64)

    from sklearn.cluster import AgglomerativeClustering

    clusterer = AgglomerativeClustering(
        n_clusters=None,
        metric="cosine",
        linkage="average",
        distance_threshold=distance_threshold,
    )
    raw_labels = clusterer.fit_predict(vecs)

    # Demote undersized clusters to noise (-1).
    counts: dict[int, int] = {}
    for lb in raw_labels:
        counts[int(lb)] = counts.get(int(lb), 0) + 1

    relabelled = np.array([
        int(lb) if counts[int(lb)] >= min_cluster_size else -1
        for lb in raw_labels
    ], dtype=np.int64)
    return relabelled


def _centroid_indices(cluster_vecs: np.ndarray,
                      cluster_idx: np.ndarray,
                      k_min: int, k_max: int) -> list[int]:
    """Pick the K chunks closest (cosine) to the mean of `cluster_vecs`.

    `cluster_idx` maps the cluster-local positions back to the original
    array. Returned indices are in the original coordinate system.
    """
    if cluster_vecs.shape[0] == 0:
        return []

    mean = cluster_vecs.mean(axis=0)
    # Re-normalise so cosine sim == dot.
    norm = np.linalg.norm(mean)
    if norm > 0:
        mean = mean / norm
    sims = cluster_vecs @ mean  # (n,)
    # Sort descending so the highest-similarity chunks come first.
    order = np.argsort(-sims)
    k = min(k_max, max(k_min, cluster_vecs.shape[0]))
    k = min(k, cluster_vecs.shape[0])
    picked_local = order[:k]
    return [int(cluster_idx[i]) for i in picked_local]


# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------

def group_by_l2(chunks: Iterable[dict]) -> dict[str, list[dict]]:
    """Return {L2_Topic -> list of chunks} using the chunks' L2_Topic field.

    Chunks missing L2_Topic are silently dropped — they haven't been
    through Phase 3.1 so there's nothing for L3 to do with them.
    """
    groups: dict[str, list[dict]] = {}
    for c in chunks:
        l2 = c.get("L2_Topic")
        if not l2:
            continue
        groups.setdefault(l2, []).append(c)
    return groups


def _join_centroid_text(chunks: list[dict], indices: list[int],
                        per_chunk_cap: int = _CENTROID_CHAR_CAP) -> str:
    """Stitch centroid chunk texts into the namer payload.

    Each chunk is headed with its chunk_id so the model can disambiguate
    sample boundaries. Truncation is per-chunk, not across-chunk, which
    preserves representation balance when one centroid is much longer.
    """
    parts: list[str] = []
    for i in indices:
        c = chunks[i]
        text = (c.get("fused_text") or "")[:per_chunk_cap]
        parts.append(f"[Chunk {c.get('chunk_id', '?')}]\n{text}")
    return "\n\n---\n\n".join(parts)


def discover_l3_for_l2(l2_chunks: list[dict],
                       l2_topic: str,
                       embedder: Embedder,
                       namer: SubTopicNamer,
                       *,
                       distance_threshold: float = DEFAULT_DISTANCE_THRESHOLD,
                       min_cluster_size: int = DEFAULT_MIN_CLUSTER_SIZE,
                       k_min: int = DEFAULT_CENTROIDS_K_MIN,
                       k_max: int = DEFAULT_CENTROIDS_K_MAX,
                       ) -> tuple[list[dict], list[ClusterAudit]]:
    """Run cluster-then-label over one L2 bucket.

    Returns (labelled_chunks, cluster_audits). Input chunks are deep-copied,
    the copies are mutated, and returned.
    """
    if not l2_chunks:
        return [], []

    # 1. Embed once per chunk.
    texts = [c.get("fused_text") or "" for c in l2_chunks]
    vecs = embedder.embed(texts)  # (n, d), L2-normalised

    # 2. Cluster.
    labels = _cluster_labels(vecs, distance_threshold, min_cluster_size)
    unique_labels = sorted(set(labels.tolist()))

    out_chunks: list[dict] = [copy.deepcopy(c) for c in l2_chunks]
    audits: list[ClusterAudit] = []

    # 3. Per-cluster naming.
    noise_l3 = f"General {l2_topic}"
    for lb in unique_labels:
        idx = np.where(labels == lb)[0]
        members = [l2_chunks[i] for i in idx]
        member_ids = [m.get("chunk_id", "?") for m in members]

        if lb == -1:
            # Apply the canned noise label. No LLM call.
            for i in idx:
                out_chunks[i]["L3_Sub_Topic"] = noise_l3
                out_chunks[i]["L3_Source"] = "noise"
            audits.append(ClusterAudit(
                cluster_id=-1, l2_topic=l2_topic, size=len(idx),
                member_chunk_ids=member_ids,
                centroid_chunk_ids=[],
                centroid_text_preview="",
                l3_sub_topic=noise_l3,
                justification="chunks below min_cluster_size; assigned fallback label",
                namer_raw=None,
            ))
            continue

        # Pick centroid chunks.
        cluster_vecs = vecs[idx]
        centroid_idx_global = _centroid_indices(cluster_vecs, idx, k_min, k_max)
        centroid_ids = [l2_chunks[i].get("chunk_id", "?") for i in centroid_idx_global]
        centroid_text = _join_centroid_text(l2_chunks, centroid_idx_global)

        # Call the namer.
        try:
            response = namer.name(l2_topic=l2_topic, centroid_text=centroid_text)
            l3_name = response["l3_sub_topic"]
            justification = response.get("justification", "")
            source = "namer"
        except Exception as exc:
            # Fall back gracefully; downstream callers can re-run later.
            l3_name = noise_l3
            justification = f"namer error: {exc!r}"
            response = None
            source = "namer_error"

        for i in idx:
            out_chunks[i]["L3_Sub_Topic"] = l3_name
            out_chunks[i]["L3_Source"] = source

        audits.append(ClusterAudit(
            cluster_id=int(lb), l2_topic=l2_topic, size=len(idx),
            member_chunk_ids=member_ids,
            centroid_chunk_ids=centroid_ids,
            centroid_text_preview=centroid_text[:200],
            l3_sub_topic=l3_name,
            justification=justification,
            namer_raw=response,
        ))

    return out_chunks, audits
