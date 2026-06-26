"""Phase 3.1 — L1 domain + L2 topic router.

Public entry points:
  - route_chunk   (single-chunk router)
  - route_chunks  (batch driver)
  - TopicRouter   (stateful helper that pre-embeds L2 anchor vectors)
"""
from .router import (
    TopicRouter,
    RouterResult,
    route_chunk,
    route_chunks,
    ANCHOR_SIM_THRESHOLD,
    L1_DOMAIN_BY_CUSTGROUP,
)
from .l4_extractor import (
    L4ExtractionNode,
    L4Result,
    extract_l4_batch,
)
from .l3_discovery import (
    ClusterAudit,
    discover_l3_for_l2,
    group_by_l2,
)
from .providers import (
    Embedder,
    TopicGenerator,
    EntityExtractor,
    SubTopicNamer,
    SentenceTransformerEmbedder,
    GeminiEmbedder,
    GoogleGeminiGenerator,
    VertexGeminiGenerator,
    GoogleGeminiEntityExtractor,
    VertexGeminiEntityExtractor,
    GoogleGeminiSubTopicNamer,
    VertexGeminiSubTopicNamer,
    DummyEmbedder,
    DummyGenerator,
    DummyEntityExtractor,
    DummySubTopicNamer,
    make_embedder,
    make_generator,
    make_extractor,
    make_namer,
)

__all__ = [
    # router
    "TopicRouter", "RouterResult", "route_chunk", "route_chunks",
    "ANCHOR_SIM_THRESHOLD", "L1_DOMAIN_BY_CUSTGROUP",
    # L4
    "L4ExtractionNode", "L4Result", "extract_l4_batch",
    # L3
    "ClusterAudit", "discover_l3_for_l2", "group_by_l2",
    # protocols + implementations
    "Embedder", "TopicGenerator", "EntityExtractor", "SubTopicNamer",
    "SentenceTransformerEmbedder", "GeminiEmbedder",
    "GoogleGeminiGenerator", "VertexGeminiGenerator",
    "GoogleGeminiEntityExtractor", "VertexGeminiEntityExtractor",
    "GoogleGeminiSubTopicNamer", "VertexGeminiSubTopicNamer",
    "DummyEmbedder", "DummyGenerator",
    "DummyEntityExtractor", "DummySubTopicNamer",
    "make_embedder", "make_generator", "make_extractor", "make_namer",
]
