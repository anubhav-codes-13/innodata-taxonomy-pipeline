Insight Engine — End-to-End Product Overview
What the product is
An AI-powered legal content enrichment platform that ingests raw legal XML documents (Wolters Kluwer KLI repositories — Kluwer Arbitration, Kluwer Competition Law, KIPL, etc.) and transforms them into RAG-ready, knowledge-graph-ready, semantically enriched content with a complete 4-level taxonomy — zero human curation required.

Demonstrated scale: 44 source XML documents → 974 retrieval chunks → fully enriched in ~90 minutes on a free-tier API key.

1. Core Capabilities (what the product does)
#	Capability	Business value
1	XML ingestion & normalization	Handles 5 legal doc types (commentary, case-note, treatise, journal article, legislation) through a single clean schema
2	Data-quality landmine repair	Auto-fixes DOCTYPE entity subsets, legacy comment blocks, page processing instructions — 100% parse success
3	Semantic chunking	Paragraph-Group Chunking (target 500w, never splits mid-paragraph) with Prefix-Fusion lineage breadcrumbs
4	4-Level Taxonomy Enrichment	L1 Domain → L2 Macro-Topic → L3 Sub-Topic → L4 Entities + Keywords
5	Cost-optimized routing (Anchor-or-Expand gate)	84.6% of decisions made with cheap embedding cosine — no LLM call
6	Cluster-then-Label sub-topic discovery	Unsupervised agglomerative clustering, then LLM names the cluster — deterministic & consistent
7	Structured entity extraction	Cases, statutes, organizations via Gemini structured-output JSON schema
8	Document-level synthesis	Word-weighted L2 ranking, case-folded entity dedup, provenance summary
9	Before/After comparison visualizer	Auditable proof of enrichment uplift per document
10	Dictionary expansion	Discovered taxonomy promoted back into seed for next iteration (self-improving)
2. The 4-Level Taxonomy (the conceptual core)
Level	Name	Mechanism	Example
L1	Domain	Deterministic (from cust_groups)	International Arbitration / Competition Law
L2	Macro-Topic	Embedding anchor + LLM expand	State Immunity, Merger Control
L3	Sub-Topic	Unsupervised clustering + LLM naming	ICSID Waiver of Immunity, Combination Notification Requirements
L4	Entities + Keywords	LLM structured extraction with dictionary validation	Halliburton v. Chubb, Article 22 EUMR
3. Pipeline Architecture (4 phases)
Phase 1 — Parse: XML → JSON (normalize 5 doc types, strip landmines)
Phase 2 — Chunk + Dictionary + Graph: Semantic chunking + master dictionary + relationship graph (xref edges)
Phase 3 — Enrichment:

3.1 Router (L1 + L2 anchor-or-expand)
3.2 L4 Entity & Keyword Extractor
3.3 L3 Cluster-then-Label Discovery Phase 4 — Synthesis: Document rollup + Before/After visualizer + Dictionary expansion
4. Demonstrated Business Impact (Before vs After)
Metric	Before (editorial XML)	After (pipeline)	Multiplier
L2 Macro-Topics (KA)	1	65	65×
L2 Macro-Topics (KCL)	5	69	14×
L3 Sub-topics	0	123	∞
L4 Keywords (KCL)	6	1,361	227×
Case citations	0	687	∞
Statute references	0	1,059	∞
Organizations	3	1,271	424×
Docs with topic tag	30%	100%	3.3×
Docs with keyword tag	14%	100%	7×
Docs with case-citation index	0%	71%	∞
5. Technology Stack
LLM: Gemini 2.5 Flash (structured JSON output)
Embeddings: gemini-embedding-001 (3072-d), with bge-small (384-d) fallback
Clustering: scikit-learn AgglomerativeClustering (cosine, threshold-based)
Providers: Pluggable architecture — Gemini API, Vertex AI, Sentence-Transformers, Dummy
Language: Python
Output format: Canonical JSON artifacts at every phase (resumable, auditable, parallelizable)
6. Key Engineering Features (production-ready)
Resumable — doc-by-doc checkpointing
Self-calibrated thresholds — embedder advertises its own anchor threshold
Defensive validation — post-LLM dictionary validation ensures controlled vocabulary
Retry with backoff — 4-retry exponential backoff on 429/503
Provenance tracking — every chunk records L2_Source (anchor/generator), L2_Similarity
Deterministic — agglomerative clustering, stable ranking (word_weight → chunk_count → name)
Auditable — every intermediate artifact on disk in human-readable JSON
7. Cost & Efficiency Story
84.6% of L2 routing decisions cost zero LLM-generation calls (anchored via embeddings only)
~3,200 total Gemini API calls for full 974-chunk corpus (vs. ~4,000+ without anchor gate)
~90 min wall-clock on free-tier API; ~10–15 min on paid Vertex
Anchor savings compound — at production scale (1000-topic seed dictionary), anchor rates climb above 95%
8. Deliverables / Output Products
Artifact	Consumer
enriched_chunks.json	Vector DB / RAG retrieval layer
final_enriched_documents.json	Search index, AI assistant grounding, document catalog
enriched_dictionary.json	Taxonomy management, seed-iteration loop
relationship_graph.json	Knowledge graph (xref edges between docs)
compare_all.txt	Editorial QA, before/after audits
master_dictionary.json	Domain-partitioned controlled vocabulary
9. Downstream Product Use Cases
AI-powered semantic search across legal repositories
AI legal assistant grounded in 4-level taxonomy facets
Knowledge graph linking cases, statutes, organizations
Entity-aware citation highlighting in reader UI
Facet filtering in search ("Show Merger Control + Gatekeeper Regulation only")
Auto-tagging of newly published documents
Editorial QA assist — flag docs that need human review
Cross-document discovery — find all docs citing Article 22 EUMR
10. Extensibility (proposal selling points)
Add new domain (KIPL, KCH, etc.) → add a block to seed_topics.json — no code change
Swap LLM → implement provider protocol, register it
Swap embedder → implement Embedder protocol with recommended_anchor_threshold
Scale to larger corpora → trivially parallelized (each doc independent)