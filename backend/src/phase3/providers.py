"""
Provider abstractions for Phase 3 — embeddings and topic-proposal generation.

We keep the router itself provider-agnostic: it depends only on the
`Embedder` and `TopicGenerator` protocols below. Concrete implementations
for Sentence-Transformers (HF bge-small), google-generativeai (Gemini
developer API), and Vertex AI (Gemini via Vertex) are bundled here. Dummy
implementations are included so the router can be smoke-tested end-to-end
with zero credentials.

All heavy dependencies (torch, google-cloud-aiplatform, google-generativeai)
are imported lazily inside the relevant class — this module is safe to
import in environments that only need the dummies.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Iterable, Protocol

try:
    import numpy as np
except ImportError:  # pragma: no cover — numpy is a hard runtime dep here
    raise


# Load .env once at import time so downstream code can rely on env vars
# (GOOGLE_API_KEY, GOOGLE_CLOUD_PROJECT, etc.) being present without each
# caller having to remember to call load_dotenv(). We walk up from this
# file until we hit a .env or the filesystem root — this keeps it working
# whether the script is launched from the repo root or a subfolder.
def _load_env_once() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return  # python-dotenv optional; silently skip if not installed
    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        candidate = parent / ".env"
        if candidate.is_file():
            load_dotenv(candidate)
            return


_load_env_once()


# Default Gemini model used across both GoogleGeminiGenerator and
# VertexGeminiGenerator. Exposed as a module constant so callers can
# override at construction time AND so a one-line change here rolls the
# default forward when new versions ship.
DEFAULT_GEMINI_MODEL: str = "gemini-2.5-flash"

# Canonical schema string reused across generators. The same schema is
# asked for in the prompt AND structurally enforced in the API calls.
TOPIC_SCHEMA_DESCRIPTION = (
    "Return ONLY a compact JSON object with exactly these two keys:\n"
    "  proposed_l2_topic  (string, 2–4 word macro topic)\n"
    "  reasoning          (string, one sentence)\n"
    "No prose, no markdown, no code fences."
)


# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------

class Embedder(Protocol):
    """Produces L2-normalised embedding vectors for a list of strings."""

    def embed(self, texts: list[str]) -> np.ndarray:
        """Return an (n, d) float32 matrix, already L2-normalised so that
        dot-product equals cosine similarity."""
        ...


class TopicGenerator(Protocol):
    """Generates a proposed L2 topic for a text chunk."""

    def propose_topic(self, l1_domain: str, existing_l2s: list[str], text: str) -> dict:
        """Return a dict with keys {proposed_l2_topic, reasoning}.

        Implementations MUST raise on parse failure so callers can log and
        skip rather than propagate bogus topics silently. The `text` passed
        in is already trimmed to a safe size by the router.
        """
        ...


class EntityExtractor(Protocol):
    """Extracts L4 entities + anchored/new keywords for a text chunk.

    Separate from TopicGenerator because the prompt, schema, and model
    config are distinct. Sharing a generator implementation would tangle
    the two nodes.
    """

    def extract(self, domain_existing_keywords: list[str], text: str) -> dict:
        """Return the canonical L4 dict (see _normalise_l4_response)."""
        ...


class SubTopicNamer(Protocol):
    """Generates an L3 sub-topic name for a cluster of chunks under an L2.

    The caller (Phase 3.3) selects 3–5 centroid chunks from each cluster
    and passes their concatenated text in as `centroid_text`.
    """

    def name(self, l2_topic: str, centroid_text: str) -> dict:
        """Return a dict with keys {l3_sub_topic, justification}."""
        ...


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _l2_normalise(matrix: np.ndarray) -> np.ndarray:
    """Row-wise L2 normalise. Zero vectors are left as zeros."""
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return (matrix / norms).astype(np.float32)


def _build_taxonomist_prompt(l1_domain: str, existing_l2s: list[str], text: str) -> str:
    """Render the system+user prompt per the Phase-3.1 spec.

    The {list_of_existing_L2s_for_this_domain} slot is rendered as a
    deterministic, sorted, comma-separated list so the same chunk+inventory
    produces the same model input (helps reproducibility and caching).
    """
    existing_rendered = ", ".join(sorted({s.strip() for s in existing_l2s if s and s.strip()}))
    if not existing_rendered:
        existing_rendered = "(none yet — propose a foundational category)"
    return (
        "Role: You are an expert Legal Taxonomist classifying enterprise "
        "legal documents.\n"
        f"Task: You are evaluating a text chunk from the domain of {l1_domain}. "
        f"The chunk did not strongly match our existing macro-topics: "
        f"{existing_rendered}.\n"
        "Read the provided text and propose a new, broad 'L2 Macro-Topic' "
        "that captures the primary legal subject of the text.\n"
        "\n"
        "Rules:\n"
        "- The topic must be broad enough to encompass multiple documents "
        "(e.g., 'Digital Markets', 'State Immunity'), NOT a highly specific "
        "keyword.\n"
        "- Output strictly in the requested JSON format.\n"
        "\n"
        f"{TOPIC_SCHEMA_DESCRIPTION}\n"
        "\n"
        "TEXT CHUNK:\n"
        f"{text}\n"
    )


def _parse_json_object(raw: str) -> dict:
    """Tolerant JSON parser: strips code fences, locates the first {...} block.

    Shared by all generator/extractor implementations. Callers add their
    own required-key validation on top.
    """
    if not raw:
        raise ValueError("empty model response")
    s = raw.strip()
    # Strip ```json ... ``` fences some models emit despite instructions.
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:].lstrip()
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError(f"no JSON object found in response: {raw[:200]!r}")
    return json.loads(s[start:end + 1])


def _parse_topic_json(raw: str) -> dict:
    """Parse + validate a topic-proposal response."""
    obj = _parse_json_object(raw)
    if "proposed_l2_topic" not in obj:
        raise ValueError(f"missing 'proposed_l2_topic' in response: {obj}")
    obj.setdefault("reasoning", "")
    # Trim extra whitespace that models sometimes pad into topics.
    obj["proposed_l2_topic"] = str(obj["proposed_l2_topic"]).strip()
    obj["reasoning"] = str(obj["reasoning"]).strip()
    return obj


# ---------------------------------------------------------------------------
# Phase 3.2 — L4 entity + keyword extractor
# ---------------------------------------------------------------------------

L4_SCHEMA_DESCRIPTION = (
    "Return ONLY a compact JSON object with exactly this shape:\n"
    '  {\n'
    '    "entities": {\n'
    '      "case_names": [string, ...],\n'
    '      "statutes_and_regulations": [string, ...],\n'
    '      "organizations": [string, ...]\n'
    '    },\n'
    '    "keywords": {\n'
    '      "existing_matched_keywords": [string, ...],\n'
    '      "new_extracted_keywords": [string, ...]\n'
    '    }\n'
    '  }\n'
    "Empty arrays are fine when nothing of that kind is present in the text.\n"
    "No prose, no markdown, no code fences."
)


def _build_extractor_prompt(domain_existing_keywords: list[str], text: str) -> str:
    """Render the Phase-3.2 entity-extractor prompt.

    The dictionary list is rendered deterministically (sorted, comma-joined)
    for reproducibility, matching the style of the L2 router prompt.
    """
    rendered = ", ".join(sorted({s.strip() for s in domain_existing_keywords if s and s.strip()}))
    if not rendered:
        rendered = "(empty — no anchor dictionary yet)"
    return (
        "Role: You are an expert Legal Information Extractor.\n"
        "Task: Read the provided legal text. Extract highly granular "
        "entities and conceptual keywords (the 'L4 layer').\n"
        "\n"
        "Instructions:\n"
        "- Entities: Extract any specific Case Names, Statutes/Regulations, "
        "and Organizations mentioned in the text.\n"
        "- Keywords: Extract 2 to 5 highly specific legal concepts.\n"
        f"- Anchoring: Here is the established dictionary of keywords for "
        f"this domain: {rendered}. If an extracted concept semantically "
        "matches one of these existing keywords, you MUST use the exact "
        "string from the dictionary. Only generate a new keyword if the "
        "concept is completely absent from the provided list.\n"
        "\n"
        f"{L4_SCHEMA_DESCRIPTION}\n"
        "\n"
        "TEXT CHUNK:\n"
        f"{text}\n"
    )


def _normalise_l4_response(obj: dict) -> dict:
    """Validate + coerce an L4 response into the canonical shape.

    Missing keys are filled with empty lists so downstream code can assume
    the full structure. String values inside lists are stripped; empty
    strings are dropped. Non-list values for list-valued keys are coerced
    to single-element lists.
    """
    def _as_str_list(v) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            v = [v]
        if not isinstance(v, list):
            return []
        out: list[str] = []
        for item in v:
            s = str(item).strip()
            if s:
                out.append(s)
        # Dedupe preserving order.
        seen: set[str] = set()
        deduped: list[str] = []
        for s in out:
            if s not in seen:
                seen.add(s)
                deduped.append(s)
        return deduped

    entities_raw = obj.get("entities") or {}
    keywords_raw = obj.get("keywords") or {}
    if not isinstance(entities_raw, dict):
        entities_raw = {}
    if not isinstance(keywords_raw, dict):
        keywords_raw = {}

    return {
        "entities": {
            "case_names":               _as_str_list(entities_raw.get("case_names")),
            "statutes_and_regulations": _as_str_list(entities_raw.get("statutes_and_regulations")),
            "organizations":            _as_str_list(entities_raw.get("organizations")),
        },
        "keywords": {
            "existing_matched_keywords": _as_str_list(keywords_raw.get("existing_matched_keywords")),
            "new_extracted_keywords":    _as_str_list(keywords_raw.get("new_extracted_keywords")),
        },
    }


def _parse_l4_json(raw: str) -> dict:
    """Parse + validate an L4 extraction response."""
    obj = _parse_json_object(raw)
    return _normalise_l4_response(obj)


# ---------------------------------------------------------------------------
# Concrete embedders
# ---------------------------------------------------------------------------

class SentenceTransformerEmbedder:
    """HF sentence-transformers (default model: BAAI/bge-small-en-v1.5).

    bge-small has a 384-d output, ~33MB on disk, and is pre-normalised when
    passed `normalize_embeddings=True`. Good baseline for local dev.
    """

    # Calibrated cosine threshold at which the router should treat a chunk
    # as "clearly matching" an existing L2 anchor. bge-small similarities
    # push into 0.85+ for genuine semantic matches on legal prose, so the
    # spec's original 0.85 value applies directly here.
    recommended_anchor_threshold: float = 0.85

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5",
                 device: str | None = None) -> None:
        from sentence_transformers import SentenceTransformer
        self.model_name = model_name
        self._model = SentenceTransformer(model_name, device=device)

    def embed(self, texts: list[str]) -> np.ndarray:
        vecs = self._model.encode(
            texts, normalize_embeddings=True,
            show_progress_bar=False, convert_to_numpy=True,
        )
        return vecs.astype(np.float32)


class GeminiEmbedder:
    """Gemini embeddings via the Google GenAI developer SDK.

    Model default is `gemini-embedding-001` (the v1 embedding model exposed
    to consumer API keys; `text-embedding-004` exists but is Vertex-only on
    many projects). Uses the same API key as the generator/extractor
    classes (GOOGLE_API_KEY / GEMINI_API_KEY), so a single .env entry
    covers the whole Phase 3 stack.

    Task type affects what the model optimises for. We default to
    `RETRIEVAL_DOCUMENT` because our downstream use is cosine similarity
    against other document-style vectors (chunks vs chunks, chunks vs L2
    topic strings). For pure symmetric similarity (e.g. duplicate
    detection) `SEMANTIC_SIMILARITY` is a better fit — override via
    `task_type=`.

    Batching note: the SDK exposes per-call embedding, so we loop here.
    For larger corpora consider switching to batch endpoints once we
    migrate to google-genai (the successor SDK).
    """

    # Calibrated cosine threshold for L2 anchoring. gemini-embedding-001
    # tends to peak around 0.82–0.84 for strongly related legal content —
    # the spec's 0.85 value would almost never anchor. Empirically 0.75
    # gave 10/12 correct anchors with 0 false positives on the demo batch.
    recommended_anchor_threshold: float = 0.75

    # Free-tier quota on gemini-embedding-001 is tight (a few calls/sec).
    # When a 429 fires, we back off 2^attempt seconds before retrying.
    _MAX_RETRIES: int = 4

    def __init__(self, model_name: str = "gemini-embedding-001",
                 task_type: str = "RETRIEVAL_DOCUMENT",
                 api_key: str | None = None) -> None:
        import google.generativeai as genai
        api_key = api_key or os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GeminiEmbedder: set GOOGLE_API_KEY in .env or the environment, "
                "or pass api_key="
            )
        genai.configure(api_key=api_key)
        self._genai = genai
        self.model_name = model_name
        self.task_type = task_type

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            # Dimension is fixed per model; we return (0,0) so callers
            # using dot products short-circuit correctly.
            return np.zeros((0, 0), dtype=np.float32)
        vectors: list[list[float]] = []
        for t in texts:
            # The SDK accepts a single string per call and rejects empty
            # strings. Substitute a single space to keep vector counts
            # aligned with input lengths (caller's bookkeeping is simpler).
            payload = t if (t and t.strip()) else " "
            vectors.append(self._embed_one_with_backoff(payload))
        matrix = np.asarray(vectors, dtype=np.float32)
        # Model returns approximately-unit vectors; re-normalise defensively
        # so `matrix @ other.T` is exactly cosine.
        return _l2_normalise(matrix)

    def _embed_one_with_backoff(self, payload: str) -> list[float]:
        """Single-shot embed with exponential backoff on 429 / 503.

        We import lazily so the module stays importable without
        google.api_core being present.
        """
        import time
        try:
            from google.api_core import exceptions as gax_exc
            retryable = (gax_exc.ResourceExhausted, gax_exc.ServiceUnavailable,
                         gax_exc.DeadlineExceeded)
        except ImportError:  # pragma: no cover
            retryable = (Exception,)

        # Per-request hard timeout. Without this, a silently-stalled
        # gRPC call can hang forever — we hit this in production during
        # the first 42-doc POC run (22 docs in, then no progress for
        # 30+ minutes on a 1-chunk doc that should have taken seconds).
        per_request_timeout_s: float = 30.0

        for attempt in range(self._MAX_RETRIES + 1):
            try:
                resp = self._genai.embed_content(
                    model=self.model_name,
                    content=payload,
                    task_type=self.task_type,
                    request_options={"timeout": per_request_timeout_s},
                )
                return resp["embedding"]
            except retryable as exc:
                if attempt == self._MAX_RETRIES:
                    raise
                delay = 2 ** attempt
                print(f"[GeminiEmbedder] transient {type(exc).__name__}; "
                      f"retrying in {delay}s (attempt {attempt + 1}/"
                      f"{self._MAX_RETRIES})", file=__import__('sys').stderr)
                time.sleep(delay)
        # Unreachable — the loop always returns or raises above.
        raise RuntimeError("unreachable")


class DummyEmbedder:
    """Deterministic hashing-based embedder for tests / offline smoke runs.

    Produces stable vectors (same string -> same vector) with enough signal
    that identical / near-identical strings score high cosine similarity.
    NOT for production — it's just so the router can be exercised without
    pulling 100MB of models.
    """

    # Dummy vectors are near-orthogonal for any two different strings, so
    # 0.30 is a reasonable anchor threshold just to let the code paths
    # exercise. Never use for real routing decisions.
    recommended_anchor_threshold: float = 0.30

    def __init__(self, dim: int = 384, seed: int = 42) -> None:
        self.dim = dim
        self.seed = seed

    def embed(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, text in enumerate(texts):
            # Bag-of-words-style signal: hash each word to an axis and sum.
            words = [w.lower() for w in (text or "").split() if w]
            for w in words:
                idx = (hash((self.seed, w)) & 0x7fffffff) % self.dim
                out[i, idx] += 1.0
        return _l2_normalise(out)


# ---------------------------------------------------------------------------
# Concrete generators
# ---------------------------------------------------------------------------

class GoogleGeminiGenerator:
    """Gemini via the developer API (google-generativeai).

    Picks up GOOGLE_API_KEY / GEMINI_API_KEY from the environment (including
    a project-level .env loaded at module import).

    Uses response_mime_type=application/json + response_schema to coerce
    output to the required shape.

    NOTE: google.generativeai has been marked deprecated by Google in favour
    of `google.genai`. We stay on the deprecated SDK for now because (a) it
    still works, and (b) switching SDKs is a separate, broader change that
    also affects any LangChain / other integrations. Revisit when adopting
    LangGraph Phase 3.2 properly.
    """

    def __init__(self, model_name: str = DEFAULT_GEMINI_MODEL,
                 api_key: str | None = None) -> None:
        import google.generativeai as genai
        api_key = api_key or os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GoogleGeminiGenerator: set GOOGLE_API_KEY in .env or the "
                "environment, or pass api_key="
            )
        genai.configure(api_key=api_key)
        self._genai = genai
        self.model_name = model_name
        self._model = genai.GenerativeModel(model_name)
        self._schema = {
            "type": "object",
            "properties": {
                "proposed_l2_topic": {"type": "string"},
                "reasoning":         {"type": "string"},
            },
            "required": ["proposed_l2_topic", "reasoning"],
        }

    def propose_topic(self, l1_domain: str, existing_l2s: list[str], text: str) -> dict:
        prompt = _build_taxonomist_prompt(l1_domain, existing_l2s, text)
        resp = self._model.generate_content(
            prompt,
            generation_config={
                "response_mime_type": "application/json",
                "response_schema": self._schema,
                "temperature": 0.2,
            },
            request_options={"timeout": 60.0},
        )
        return _parse_topic_json(resp.text)


class VertexGeminiGenerator:
    """Gemini via Vertex AI SDK (google-cloud-aiplatform / vertexai).

    Expects GOOGLE_CLOUD_PROJECT + GOOGLE_CLOUD_LOCATION env vars (or pass
    them in). Uses application-default credentials.
    """

    def __init__(self, model_name: str = DEFAULT_GEMINI_MODEL,
                 project: str | None = None, location: str | None = None) -> None:
        import vertexai
        from vertexai.generative_models import GenerativeModel

        project = project or os.environ.get("GOOGLE_CLOUD_PROJECT")
        location = location or os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
        if not project:
            raise RuntimeError("VertexGeminiGenerator: GOOGLE_CLOUD_PROJECT not set")
        vertexai.init(project=project, location=location)
        self._model = GenerativeModel(model_name)
        self._schema = {
            "type": "OBJECT",
            "properties": {
                "proposed_l2_topic": {"type": "STRING"},
                "reasoning":         {"type": "STRING"},
            },
            "required": ["proposed_l2_topic", "reasoning"],
        }

    def propose_topic(self, l1_domain: str, existing_l2s: list[str], text: str) -> dict:
        prompt = _build_taxonomist_prompt(l1_domain, existing_l2s, text)
        resp = self._model.generate_content(
            prompt,
            generation_config={
                "response_mime_type": "application/json",
                "response_schema": self._schema,
                "temperature": 0.2,
            },
        )
        return _parse_topic_json(resp.text)


class DummyGenerator:
    """Offline generator that derives a plausible topic from chunk context.

    Picks the top-frequency capitalised 2-gram from the chunk text as a
    stand-in topic. Useful for:
      * unit tests
      * demonstrating the Expand path end-to-end without a paid API call
      * establishing the output contract (dict w/ proposed_l2_topic +
        reasoning) so the router code paths can be exercised

    Do NOT use for production — the "topics" it proposes are naive and
    inconsistent across semantically equivalent chunks.
    """

    def propose_topic(self, l1_domain: str, existing_l2s: list[str], text: str) -> dict:
        import re
        from collections import Counter

        # Pull capitalised bigrams ("Generative AI", "Digital Markets").
        bigrams = re.findall(r"\b([A-Z][a-z]+)\s+([A-Z][A-Za-z]+)\b", text or "")
        counter = Counter(f"{a} {b}" for a, b in bigrams)
        existing_set = {s.strip() for s in existing_l2s}
        candidate = next(
            (t for t, _ in counter.most_common() if t not in existing_set),
            None,
        )
        if not candidate:
            # Fall back to the first 3 alphabetic words, title-cased.
            words = re.findall(r"[A-Za-z]+", text or "")[:3]
            candidate = (" ".join(words) or "Uncategorised").title()
        return {
            "proposed_l2_topic": candidate,
            "reasoning": (
                f"[DummyGenerator] L1={l1_domain}; "
                f"candidate chosen from most-frequent new capitalised bigram; "
                f"existing L2s did not cover this concept."
            ),
        }


# ---------------------------------------------------------------------------
# Concrete entity extractors (Phase 3.2)
# ---------------------------------------------------------------------------

# Schemas for the structured-output mode. Google (developer) SDK uses
# lowercase "type"; Vertex uses uppercase.
_L4_RESPONSE_SCHEMA_GOOGLE = {
    "type": "object",
    "properties": {
        "entities": {
            "type": "object",
            "properties": {
                "case_names":               {"type": "array", "items": {"type": "string"}},
                "statutes_and_regulations": {"type": "array", "items": {"type": "string"}},
                "organizations":            {"type": "array", "items": {"type": "string"}},
            },
            "required": ["case_names", "statutes_and_regulations", "organizations"],
        },
        "keywords": {
            "type": "object",
            "properties": {
                "existing_matched_keywords": {"type": "array", "items": {"type": "string"}},
                "new_extracted_keywords":    {"type": "array", "items": {"type": "string"}},
            },
            "required": ["existing_matched_keywords", "new_extracted_keywords"],
        },
    },
    "required": ["entities", "keywords"],
}

_L4_RESPONSE_SCHEMA_VERTEX = {
    "type": "OBJECT",
    "properties": {
        "entities": {
            "type": "OBJECT",
            "properties": {
                "case_names":               {"type": "ARRAY", "items": {"type": "STRING"}},
                "statutes_and_regulations": {"type": "ARRAY", "items": {"type": "STRING"}},
                "organizations":            {"type": "ARRAY", "items": {"type": "STRING"}},
            },
            "required": ["case_names", "statutes_and_regulations", "organizations"],
        },
        "keywords": {
            "type": "OBJECT",
            "properties": {
                "existing_matched_keywords": {"type": "ARRAY", "items": {"type": "STRING"}},
                "new_extracted_keywords":    {"type": "ARRAY", "items": {"type": "STRING"}},
            },
            "required": ["existing_matched_keywords", "new_extracted_keywords"],
        },
    },
    "required": ["entities", "keywords"],
}


class GoogleGeminiEntityExtractor:
    """L4 entity + keyword extractor via the Google GenAI developer SDK.

    Uses the same env-var conventions as GoogleGeminiGenerator; in practice
    the two can share a single API key.
    """

    def __init__(self, model_name: str = DEFAULT_GEMINI_MODEL,
                 api_key: str | None = None) -> None:
        import google.generativeai as genai
        api_key = api_key or os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GoogleGeminiEntityExtractor: set GOOGLE_API_KEY in .env or the "
                "environment, or pass api_key="
            )
        genai.configure(api_key=api_key)
        self.model_name = model_name
        self._model = genai.GenerativeModel(model_name)
        self._schema = _L4_RESPONSE_SCHEMA_GOOGLE

    def extract(self, domain_existing_keywords: list[str], text: str) -> dict:
        prompt = _build_extractor_prompt(domain_existing_keywords, text)
        resp = self._model.generate_content(
            prompt,
            generation_config={
                "response_mime_type": "application/json",
                "response_schema": self._schema,
                # Slightly higher than the topic generator — entity
                # extraction benefits from a bit of variance when listing
                # things it saw in the text. Still low to keep determinism.
                "temperature": 0.2,
            },
            request_options={"timeout": 60.0},
        )
        return _parse_l4_json(resp.text)


class VertexGeminiEntityExtractor:
    """L4 extractor via the Vertex AI SDK."""

    def __init__(self, model_name: str = DEFAULT_GEMINI_MODEL,
                 project: str | None = None, location: str | None = None) -> None:
        import vertexai
        from vertexai.generative_models import GenerativeModel

        project = project or os.environ.get("GOOGLE_CLOUD_PROJECT")
        location = location or os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
        if not project:
            raise RuntimeError("VertexGeminiEntityExtractor: GOOGLE_CLOUD_PROJECT not set")
        vertexai.init(project=project, location=location)
        self.model_name = model_name
        self._model = GenerativeModel(model_name)
        self._schema = _L4_RESPONSE_SCHEMA_VERTEX

    def extract(self, domain_existing_keywords: list[str], text: str) -> dict:
        prompt = _build_extractor_prompt(domain_existing_keywords, text)
        resp = self._model.generate_content(
            prompt,
            generation_config={
                "response_mime_type": "application/json",
                "response_schema": self._schema,
                "temperature": 0.2,
            },
        )
        return _parse_l4_json(resp.text)


class DummyEntityExtractor:
    """Offline extractor with coarse regex heuristics.

    Exists only so the L4 node can be exercised end-to-end without a paid
    API call. Heuristics (in order):
      * case_names:               text like "X v. Y" or "X v Y"
      * statutes_and_regulations: things like "Directive 2003/55/EC",
                                   "Section 67", "Article 54"
      * organizations:            consecutive capitalised tokens ending in
                                   "Commission|Court|Centre|Authority|
                                   Tribunal" etc.
      * keywords:                 prefers exact-casing matches from the
                                   supplied dictionary; otherwise picks
                                   top capitalised bigrams as new keywords.

    Do NOT use for production. The heuristics are intentionally simple so
    developers immediately see when a DummyExtractor is in place.
    """

    _CASE_RE = re.compile(r"\b([A-Z][A-Za-z.'\-]*(?:\s+[A-Z][A-Za-z.'\-]*){0,4})\s+v\.?\s+([A-Z][A-Za-z.'\-]*(?:\s+[A-Z][A-Za-z.'\-]*){0,4})\b")
    _STATUTE_RES = [
        re.compile(r"\bDirective\s+\d{1,4}/\d{1,4}/[A-Z]{1,4}\b"),
        re.compile(r"\bRegulation\s+\(?[A-Z]{2,3}\)?\s+No?\.?\s*\d+/\d+\b", re.IGNORECASE),
        re.compile(r"\bSection\s+\d+[A-Za-z]?\b"),
        re.compile(r"\bArticle\s+\d+(?:\(\d+\))?\b"),
        re.compile(r"\b(?:Arbitration|Competition|Antitrust)\s+Act\s+\d{4}\b"),
    ]
    _ORG_RE = re.compile(
        r"\b((?:[A-Z][A-Za-z]+(?:\s+|\s+of\s+|\s+for\s+)){0,6}"
        r"(?:Commission|Court|Centre|Center|Authority|Tribunal|Institute|Committee|"
        r"Office|Agency|Council|Board|Organization|Organisation)(?:\s+of\s+[A-Z][A-Za-z]+)*)\b"
    )

    _CAPITAL_BIGRAM_RE = re.compile(r"\b([A-Z][a-z]+)\s+([A-Z][A-Za-z]+)\b")

    def extract(self, domain_existing_keywords: list[str], text: str) -> dict:
        from collections import Counter
        text = text or ""

        case_names = sorted({f"{a} v. {b}" for a, b in self._CASE_RE.findall(text)})

        statutes: list[str] = []
        seen_stat: set[str] = set()
        for pat in self._STATUTE_RES:
            for m in pat.findall(text):
                # findall returns either strings or tuples depending on groups
                s = m if isinstance(m, str) else " ".join(str(x) for x in m)
                s = s.strip()
                if s and s not in seen_stat:
                    seen_stat.add(s)
                    statutes.append(s)

        orgs: list[str] = []
        seen_org: set[str] = set()
        for m in self._ORG_RE.findall(text):
            s = (m[0] if isinstance(m, tuple) else m).strip()
            # Skip bare role words that slip through without a preceding name.
            if s and len(s.split()) >= 2 and s not in seen_org:
                seen_org.add(s)
                orgs.append(s)

        # Keywords: anchor by case-insensitive substring match against the
        # dictionary; anything unmatched falls into new_extracted_keywords.
        existing_matched: list[str] = []
        lc_text = text.lower()
        for kw in domain_existing_keywords:
            if kw and kw.lower() in lc_text:
                existing_matched.append(kw)
        existing_matched = existing_matched[:5]

        # New keywords: top-frequency capitalised bigrams not already in
        # existing matches or the dictionary.
        taken = {k.lower() for k in existing_matched} | {
            k.lower() for k in domain_existing_keywords
        }
        counter = Counter(
            f"{a} {b}" for a, b in self._CAPITAL_BIGRAM_RE.findall(text)
        )
        new_keywords: list[str] = []
        for cand, _ in counter.most_common():
            if cand.lower() in taken:
                continue
            new_keywords.append(cand)
            if len(new_keywords) >= 5 - len(existing_matched):
                break

        return _normalise_l4_response({
            "entities": {
                "case_names":               case_names,
                "statutes_and_regulations": statutes,
                "organizations":            orgs,
            },
            "keywords": {
                "existing_matched_keywords": existing_matched,
                "new_extracted_keywords":    new_keywords,
            },
        })


# ---------------------------------------------------------------------------
# Phase 3.3 — L3 sub-topic naming
# ---------------------------------------------------------------------------

L3_SCHEMA_DESCRIPTION = (
    "Return ONLY a compact JSON object with exactly these two keys:\n"
    "  l3_sub_topic    (string, 2–4 word sub-topic name)\n"
    "  justification   (string, one sentence explaining why this name fits)\n"
    "No prose, no markdown, no code fences."
)


def _build_subtopic_prompt(l2_topic: str, centroid_text: str) -> str:
    """Phase-3.3 namer prompt. Texts from the cluster's centroid chunks are
    already concatenated by the caller."""
    return (
        "Role: You are an expert Legal Taxonomist.\n"
        f"Task: You are defining a Sub-Topic (L3) for a cluster of legal "
        f"documents that all fall under the Macro-Topic (L2) of {l2_topic}.\n"
        "Read the provided sample texts from this cluster. Generate a "
        "highly concise, 2-to-4 word Sub-Topic name that perfectly unites "
        "the core legal concept discussed across all samples.\n"
        "\n"
        f"{L3_SCHEMA_DESCRIPTION}\n"
        "\n"
        "SAMPLE TEXTS:\n"
        f"{centroid_text}\n"
    )


def _parse_subtopic_json(raw: str) -> dict:
    obj = _parse_json_object(raw)
    if "l3_sub_topic" not in obj:
        raise ValueError(f"missing 'l3_sub_topic' in response: {obj}")
    obj.setdefault("justification", "")
    obj["l3_sub_topic"] = str(obj["l3_sub_topic"]).strip()
    obj["justification"] = str(obj["justification"]).strip()
    return obj


_L3_RESPONSE_SCHEMA_GOOGLE = {
    "type": "object",
    "properties": {
        "l3_sub_topic":  {"type": "string"},
        "justification": {"type": "string"},
    },
    "required": ["l3_sub_topic", "justification"],
}

_L3_RESPONSE_SCHEMA_VERTEX = {
    "type": "OBJECT",
    "properties": {
        "l3_sub_topic":  {"type": "STRING"},
        "justification": {"type": "STRING"},
    },
    "required": ["l3_sub_topic", "justification"],
}


class GoogleGeminiSubTopicNamer:
    """L3 sub-topic namer via the Google GenAI developer SDK."""

    def __init__(self, model_name: str = DEFAULT_GEMINI_MODEL,
                 api_key: str | None = None) -> None:
        import google.generativeai as genai
        api_key = api_key or os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GoogleGeminiSubTopicNamer: set GOOGLE_API_KEY in .env or the "
                "environment, or pass api_key="
            )
        genai.configure(api_key=api_key)
        self.model_name = model_name
        self._model = genai.GenerativeModel(model_name)
        self._schema = _L3_RESPONSE_SCHEMA_GOOGLE

    def name(self, l2_topic: str, centroid_text: str) -> dict:
        prompt = _build_subtopic_prompt(l2_topic, centroid_text)
        resp = self._model.generate_content(
            prompt,
            generation_config={
                "response_mime_type": "application/json",
                "response_schema": self._schema,
                "temperature": 0.2,
            },
            request_options={"timeout": 60.0},
        )
        return _parse_subtopic_json(resp.text)


class VertexGeminiSubTopicNamer:
    """L3 sub-topic namer via the Vertex AI SDK."""

    def __init__(self, model_name: str = DEFAULT_GEMINI_MODEL,
                 project: str | None = None, location: str | None = None) -> None:
        import vertexai
        from vertexai.generative_models import GenerativeModel

        project = project or os.environ.get("GOOGLE_CLOUD_PROJECT")
        location = location or os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
        if not project:
            raise RuntimeError("VertexGeminiSubTopicNamer: GOOGLE_CLOUD_PROJECT not set")
        vertexai.init(project=project, location=location)
        self.model_name = model_name
        self._model = GenerativeModel(model_name)
        self._schema = _L3_RESPONSE_SCHEMA_VERTEX

    def name(self, l2_topic: str, centroid_text: str) -> dict:
        prompt = _build_subtopic_prompt(l2_topic, centroid_text)
        resp = self._model.generate_content(
            prompt,
            generation_config={
                "response_mime_type": "application/json",
                "response_schema": self._schema,
                "temperature": 0.2,
            },
        )
        return _parse_subtopic_json(resp.text)


class DummySubTopicNamer:
    """Offline namer for smoke tests.

    Picks the most frequent capitalised bigram across the centroid texts
    as the L3 name. Good enough to exercise the control flow; topics
    produced are not production quality.
    """

    def name(self, l2_topic: str, centroid_text: str) -> dict:
        from collections import Counter
        bigrams = re.findall(r"\b([A-Z][a-z]+)\s+([A-Z][A-Za-z]+)\b", centroid_text or "")
        counter = Counter(f"{a} {b}" for a, b in bigrams)
        candidate = next((t for t, _ in counter.most_common()), None)
        if not candidate:
            words = re.findall(r"[A-Za-z]+", centroid_text or "")[:3]
            candidate = (" ".join(words) or f"General {l2_topic}").title()
        return {
            "l3_sub_topic": candidate,
            "justification": (
                f"[DummySubTopicNamer] most-frequent capitalised bigram "
                f"across centroid chunks under L2={l2_topic!r}."
            ),
        }


# ---------------------------------------------------------------------------
# Factory so CLIs can pick providers by name
# ---------------------------------------------------------------------------

def make_embedder(kind: str = "gemini", **kwargs) -> Embedder:
    """Construct an embedder by name.

    Default is `gemini` (text-embedding-004 via google-generativeai). This
    keeps the Phase 3 stack on a single SDK when you don't want to pull
    torch+sentence-transformers locally.
    """
    kind = kind.lower()
    if kind in ("gemini", "google", "google-gemini", "text-embedding-004"):
        return GeminiEmbedder(**kwargs)
    if kind in ("st", "sentence-transformers", "hf", "huggingface"):
        return SentenceTransformerEmbedder(**kwargs)
    if kind == "dummy":
        return DummyEmbedder(**kwargs)
    raise ValueError(f"unknown embedder kind: {kind}")


def make_generator(kind: str = "dummy", **kwargs) -> TopicGenerator:
    kind = kind.lower()
    if kind in ("google", "gemini", "google-gemini"):
        return GoogleGeminiGenerator(**kwargs)
    if kind in ("vertex", "vertex-gemini"):
        return VertexGeminiGenerator(**kwargs)
    if kind == "dummy":
        return DummyGenerator()
    raise ValueError(f"unknown generator kind: {kind}")


def make_extractor(kind: str = "dummy", **kwargs) -> EntityExtractor:
    kind = kind.lower()
    if kind in ("google", "gemini", "google-gemini"):
        return GoogleGeminiEntityExtractor(**kwargs)
    if kind in ("vertex", "vertex-gemini"):
        return VertexGeminiEntityExtractor(**kwargs)
    if kind == "dummy":
        return DummyEntityExtractor()
    raise ValueError(f"unknown extractor kind: {kind}")


def make_namer(kind: str = "dummy", **kwargs) -> SubTopicNamer:
    kind = kind.lower()
    if kind in ("google", "gemini", "google-gemini"):
        return GoogleGeminiSubTopicNamer(**kwargs)
    if kind in ("vertex", "vertex-gemini"):
        return VertexGeminiSubTopicNamer(**kwargs)
    if kind == "dummy":
        return DummySubTopicNamer()
    raise ValueError(f"unknown namer kind: {kind}")
