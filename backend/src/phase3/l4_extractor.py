"""
Phase 3.2 — L4 entity + keyword extraction node.

Takes chunks produced by Phase 3.1 (each already tagged with L1_Domain /
L2_Topic / etc.) and enriches them with granular L4 metadata:

  L4_metadata = {
    entities: {case_names, statutes_and_regulations, organizations},
    keywords: {existing_matched_keywords, new_extracted_keywords}
  }

The node is stateless per chunk; scheduling / retry / parallelism are left
to the caller (LangGraph or a batch driver). We DO however cache the
per-domain keyword list on the extractor so the prompt rendering does not
repeatedly re-scan the master_dictionary.

Post-call validation:
  * The model is asked to echo back dictionary keywords verbatim when a
    concept matches. Models occasionally paraphrase. We defensively filter
    `existing_matched_keywords` against the real dictionary (case-sensitive
    match on the provided strings) and silently re-route anything that
    isn't an exact match into `new_extracted_keywords`. This prevents the
    downstream "controlled vocabulary" guarantee from rotting.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Iterable

from .providers import EntityExtractor


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# Max characters of fused_text sent to the extractor. Same reasoning as the
# router: cap API cost / latency for pathological chunks. Our chunker caps
# chunks at ~800 words, so this is mostly a defensive upper bound.
_MAX_EXTRACTOR_CHARS: int = 6000


# cust_group -> master_dictionary key. Mirrors router.L1_DOMAIN_BY_CUSTGROUP
# but keyed differently because this module reads by cust_group directly
# (chunks post-3.1 still carry cust_groups; using them avoids coupling to
# the L1 display label).
_DOMAIN_KEY_BY_CUSTGROUP: dict[str, str] = {
    "KA":  "KA",
    "KCL": "KCL",
}
_DOMAIN_KEY_BY_L1_LABEL: dict[str, str] = {
    "International Arbitration": "KA",
    "Competition Law":            "KCL",
}


# ---------------------------------------------------------------------------
# Result record
# ---------------------------------------------------------------------------

@dataclass
class L4Result:
    """Per-chunk audit record from the L4 node.

    `chunk` is the mutated chunk dict (a deep copy of the input).
    `l4_metadata` is exposed separately so callers can index / log without
    re-reading the chunk.
    """
    chunk_id:    str
    status:      str               # "EXTRACTED" | "SKIPPED" | "ERROR"
    domain_key:  str | None        # "KA" | "KCL" | None
    l4_metadata: dict | None
    error:       str | None = None
    chunk:       dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Domain resolution helpers
# ---------------------------------------------------------------------------

def _resolve_domain_key(chunk: dict) -> str | None:
    """Pick the single best domain key (KA / KCL) for this chunk.

    Priority:
      1. L1_Domain label set by Phase 3.1 router (most specific signal).
      2. First known value in cust_groups.
    Returns None when no known domain can be identified.
    """
    l1 = chunk.get("L1_Domain")
    if isinstance(l1, str) and l1 in _DOMAIN_KEY_BY_L1_LABEL:
        return _DOMAIN_KEY_BY_L1_LABEL[l1]
    for cg in (chunk.get("cust_groups") or []):
        key = _DOMAIN_KEY_BY_CUSTGROUP.get(cg)
        if key:
            return key
    return None


def _domain_keywords(master_dictionary: dict, domain_key: str) -> list[str]:
    block = master_dictionary.get(domain_key) or {}
    kws = block.get("keywords") or []
    return [k for k in kws if isinstance(k, str) and k.strip()]


def _validate_matched_keywords(result: dict, allowed: set[str]) -> dict:
    """Re-route anything in existing_matched_keywords that isn't literally
    in the allowed dictionary into new_extracted_keywords.

    Mutates + returns the same dict (pointer is already a fresh copy from
    _normalise_l4_response).
    """
    kw_block = result.get("keywords") or {}
    matched = kw_block.get("existing_matched_keywords") or []
    new = kw_block.get("new_extracted_keywords") or []

    real_matched: list[str] = []
    demoted: list[str] = []
    for k in matched:
        if k in allowed:
            real_matched.append(k)
        else:
            demoted.append(k)

    # Merge demoted into new_extracted_keywords (dedupe, preserve order).
    seen: set[str] = set(new)
    combined = list(new)
    for k in demoted:
        if k not in seen:
            seen.add(k)
            combined.append(k)

    kw_block["existing_matched_keywords"] = real_matched
    kw_block["new_extracted_keywords"] = combined
    result["keywords"] = kw_block
    return result


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------

class L4ExtractionNode:
    """Stateful wrapper around an EntityExtractor that caches per-domain
    keyword lists from the master dictionary. Safe to reuse across many
    chunks in a batch."""

    def __init__(self, master_dictionary: dict, extractor: EntityExtractor) -> None:
        self.master_dictionary = master_dictionary
        self.extractor = extractor
        self._kw_cache: dict[str, tuple[list[str], set[str]]] = {}

    def _keywords_for(self, domain_key: str) -> tuple[list[str], set[str]]:
        """Return (ordered_list_for_prompt, allowed_set_for_validation)."""
        hit = self._kw_cache.get(domain_key)
        if hit is not None:
            return hit
        kws = _domain_keywords(self.master_dictionary, domain_key)
        entry = (kws, set(kws))
        self._kw_cache[domain_key] = entry
        return entry

    def extract(self, chunk: dict) -> L4Result:
        chunk_id = chunk.get("chunk_id", "?")
        domain_key = _resolve_domain_key(chunk)

        if not domain_key:
            out = copy.deepcopy(chunk)
            # Record an empty L4_metadata so downstream schema is stable.
            out["L4_metadata"] = None
            return L4Result(
                chunk_id=chunk_id, status="SKIPPED",
                domain_key=None, l4_metadata=None, chunk=out,
                error="no KA/KCL domain on chunk",
            )

        keywords_list, keywords_allowed = self._keywords_for(domain_key)
        text = (chunk.get("fused_text") or "")[:_MAX_EXTRACTOR_CHARS]

        try:
            raw = self.extractor.extract(keywords_list, text)
        except Exception as exc:
            out = copy.deepcopy(chunk)
            out["L4_metadata"] = None
            return L4Result(
                chunk_id=chunk_id, status="ERROR",
                domain_key=domain_key, l4_metadata=None,
                chunk=out, error=repr(exc),
            )

        # Defensive validation: keep existing_matched strictly within the
        # supplied dictionary. Paraphrases get demoted to new_extracted.
        validated = _validate_matched_keywords(raw, keywords_allowed)

        out = copy.deepcopy(chunk)
        out["L4_metadata"] = validated
        return L4Result(
            chunk_id=chunk_id, status="EXTRACTED",
            domain_key=domain_key, l4_metadata=validated, chunk=out,
        )


# ---------------------------------------------------------------------------
# Functional batch wrapper
# ---------------------------------------------------------------------------

def extract_l4_batch(chunks: Iterable[dict],
                     master_dictionary: dict,
                     extractor: EntityExtractor) -> list[L4Result]:
    """Batch driver. Returns a list of L4Result; original chunks untouched."""
    node = L4ExtractionNode(master_dictionary, extractor)
    return [node.extract(c) for c in chunks]
