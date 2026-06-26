# Token Usage & LLM Cost Analysis — Insight Engine

Grounded analysis of token consumption per LLM call type, derived directly from the pipeline code ([src/phase3/providers.py](src/phase3/providers.py)) and the 974-chunk POC run on `data/poc_output/`.

Use this to estimate cost for any corpus size — POC (44 docs / 974 chunks) or production scale (150,000 docs / ~3.3M chunks).

---

## 1. Quick reference — token-to-word conversion

For English legal prose, the Gemini tokenizer averages **~1.3 tokens per word** (range 1.2–1.5 depending on legal jargon, citations, numerics).

| Words | Tokens (approx) |
|---:|---:|
| 100 | 130 |
| 500 | 650 |
| 800 | 1,040 |
| 1,000 | 1,300 |

Chunk sizing in the pipeline ([src/semantic_chunker.py](src/semantic_chunker.py)): **target 500 words, slack 150, hard cap 800 words** → typical chunk body **~650–1,040 tokens**.

---

## 2. LLM Call Inventory (per chunk, per document)

The pipeline makes **5 distinct LLM call types**. Each has its own prompt + output shape.

| # | Call Type | Model | Frequency | Where |
|---|---|---|---|---|
| 1 | **Embedding (initial routing)** | `gemini-embedding-001` | 1 per chunk (always) | Phase 3.1 |
| 2 | **L2 Topic generation (Expand path)** | `gemini-2.5-flash` | 1 per chunk *only if not anchored* (~15% of chunks) | Phase 3.1 |
| 3 | **L4 Entity + Keyword extraction** | `gemini-2.5-flash` | 1 per chunk (always) | Phase 3.2 |
| 4 | **Embedding (re-embed for L3 clustering)** | `gemini-embedding-001` | 1 per chunk (always) | Phase 3.3 |
| 5 | **L3 Sub-topic naming** | `gemini-2.5-flash` | 1 per L2 cluster (~1 per 8 chunks) | Phase 3.3 |

---

## 3. Per-Call Token Breakdown

### Call 1 — Embedding (Phase 3.1, initial routing)

| | Tokens |
|---|---:|
| Input (chunk fused_text) | **~700–1,100** |
| Output | n/a — returns 3,072-d vector |

**Notes:**
- Input is the chunk's `fused_text` (Prefix-Fusion breadcrumb ~30 tokens + body text)
- Cost dimension: **input tokens only** (embedding models don't have output token cost)
- L2 anchor topics are also embedded **once at init** (~20–50 topics × ~15 tokens each = ~750 tokens total, amortized)

### Call 2 — L2 Topic Generation (Phase 3.1 Expand path)

Prompt template from [providers.py:128-157](src/phase3/providers.py#L128-L157):

| | Tokens |
|---|---:|
| Prompt scaffolding (role, task, rules, schema description) | ~180 |
| Existing L2 list (sorted, comma-joined ~20–100 topics) | ~150–500 |
| Chunk text | ~700–1,040 |
| **Total input** | **~1,030–1,720** |
| Output (`{proposed_l2_topic, reasoning}`) | **~30–60** |

**Triggers only when chunk fails to anchor** — that's ~15% of chunks in POC (84.6% anchored).

### Call 3 — L4 Entity + Keyword Extraction (Phase 3.2)

Prompt template from [providers.py:215-243](src/phase3/providers.py#L215-L243):

| | Tokens |
|---|---:|
| Prompt scaffolding (role, task, instructions, schema) | ~250 |
| Domain keyword dictionary (sorted, comma-joined ~30–500 keywords) | ~200–1,500 |
| Chunk text | ~700–1,040 |
| **Total input** | **~1,150–2,790** |
| Output (entities + keywords JSON; typical chunk yields 3–8 cases, 2–5 statutes, 5–15 orgs, 5–10 keywords) | **~150–400** |

**Always runs** — 1 call per chunk.

### Call 4 — Embedding (Phase 3.3 re-embed for clustering)

| | Tokens |
|---|---:|
| Input (chunk fused_text again) | **~700–1,100** |
| Output | n/a — returns 3,072-d vector |

Same as Call 1. The pipeline re-embeds because Phase 3.1's vectors aren't persisted. **Cost-saving opportunity:** persist Phase 3.1 vectors and skip this call entirely → **~50% reduction in total embedding spend**.

### Call 5 — L3 Sub-topic Naming (Phase 3.3, per cluster)

Prompt template from [providers.py:835-850](src/phase3/providers.py#L835-L850):

| | Tokens |
|---|---:|
| Prompt scaffolding | ~120 |
| Centroid text (3–5 chunks concatenated, ~2,500–5,000 words) | **~3,250–6,500** |
| **Total input** | **~3,370–6,620** |
| Output (`{l3_sub_topic, justification}`) | **~30–60** |

**Frequency:** 1 call per L2 cluster, not per chunk. POC had 127 clusters across 974 chunks → ratio ~**1 call per 7.7 chunks**.

---

## 4. Aggregated Per-Chunk Token Profile

Using **midpoint** estimates and POC's **84.6% anchor rate**:

| Call | Probability | Input tokens (avg) | Output tokens (avg) |
|---|---:|---:|---:|
| 1. Embedding (route) | 100% | 900 | 0 |
| 2. L2 generation (Expand) | 15.4% | 1,375 | 45 |
| 3. L4 extraction | 100% | 1,970 | 275 |
| 4. Embedding (re-cluster) | 100% | 900 | 0 |
| 5. L3 naming (per cluster, amortized) | 1/7.7 | ~5,000 | 45 |

### Per-chunk totals (averaged across anchored + expanded paths)

| | Input tokens | Output tokens |
|---|---:|---:|
| **Embedding total** (Calls 1 + 4) | **~1,800** | 0 |
| **Generative total** (Calls 2 + 3 + 5 amortized) | **~2,840** | **~290** |

**Per-chunk averages:**
- Embedding model: **~1,800 input tokens**
- Generation model: **~2,840 input + ~290 output tokens**

---

## 5. Pricing — Current Public Rates (as of 2026)

### Gemini 2.5 Flash (`gemini-2.5-flash`)

| Token type | Price per 1M tokens |
|---|---:|
| Input | **$0.30** |
| Output | **$2.50** |

### Gemini Embedding (`gemini-embedding-001`)

| Token type | Price per 1M tokens |
|---|---:|
| Input | **$0.15** |

*(Use your contracted Vertex/enterprise rate if different — these are public list prices and shift over time. Always confirm before quoting a client.)*

---

## 6. Cost Per Chunk

Applying the rates above to the averaged per-chunk profile:

| Component | Tokens | Rate | Cost per chunk |
|---|---:|---:|---:|
| Embedding (1,800 input × 2 calls already summed) | 1,800 | $0.15 / 1M | **$0.00027** |
| Generation input (2,840) | 2,840 | $0.30 / 1M | **$0.00085** |
| Generation output (290) | 290 | $2.50 / 1M | **$0.00073** |
| **Total per chunk** | | | **~$0.00185** |

**≈ $0.002 per chunk** (rounded for client-facing quotes).

---

## 7. Cost Scaling Table

### POC scale — 44 documents / 974 chunks

| Component | Volume | Cost |
|---|---:|---:|
| Embedding tokens (input) | ~1.75M | **~$0.26** |
| Generation tokens (input) | ~2.77M | **~$0.83** |
| Generation tokens (output) | ~282K | **~$0.71** |
| **POC total LLM spend** | | **~$1.80** |

*(This is why the POC fit comfortably inside free-tier quota.)*

### Mid-scale — 10,000 documents / ~220,000 chunks

| Component | Volume | Cost |
|---|---:|---:|
| Embedding tokens | ~395M | **~$59** |
| Generation tokens (input) | ~625M | **~$188** |
| Generation tokens (output) | ~64M | **~$160** |
| **10k corpus LLM spend** | | **~$407** |

### Production scale — 150,000 documents / ~3.3M chunks

| Component | Volume | Cost |
|---|---:|---:|
| Embedding tokens (input) | ~5.94 billion | **~$891** |
| Generation tokens (input) | ~9.37 billion | **~$2,811** |
| Generation tokens (output) | ~957 million | **~$2,393** |
| **150k corpus LLM spend** | | **~$6,095** |

**Per-document cost at 150k scale: ~$0.041** (about 4 cents per document for complete 4-level enrichment).

---

## 8. Cost Sensitivity Levers

The total cost moves significantly based on a few key variables. Here's the impact of each:

### Lever 1 — Anchor rate

Anchor rate determines how many L2 generation calls are avoided.

| Anchor rate | Expand calls per 100 chunks | Cost delta vs. 85% baseline |
|---:|---:|---:|
| 50% (small seed dictionary) | 50 | **+15% cost** |
| 85% (POC actual) | 15 | baseline |
| 95% (mature seed dictionary, projected at 150k scale) | 5 | **–4% cost** |

### Lever 2 — Persist embeddings (eliminate re-embed in Phase 3.3)

Re-embedding doubles embedding spend. Persisting Phase 3.1 vectors and reusing them in Phase 3.3 cuts embedding cost in half:

- 150k corpus saving: **~$445** on embedding spend
- Trivial engineering change; recommended for production

### Lever 3 — Chunk size

Larger chunks = fewer chunks but more tokens per chunk. The relationship isn't linear because:
- L4 extraction output grows roughly with chunk size (more entities per chunk)
- L2 generation prompt scaffolding is fixed; bigger chunks dilute it

Current 500-word target is near-optimal for the LLM call budget. Going to 800 words would reduce chunk count by ~30% at ~20% higher per-chunk cost — net **~15% cost reduction** but at the price of retrieval precision.

### Lever 4 — Model choice

| Model | Input $/1M | Output $/1M | Relative cost vs. Flash |
|---|---:|---:|---:|
| Gemini 2.5 Flash | $0.30 | $2.50 | **1.0× (baseline)** |
| Gemini 2.5 Pro | $1.25 | $10.00 | ~4× |
| Gemini 2.5 Flash-Lite | $0.10 | $0.40 | ~0.3× |
| Claude Sonnet 4.6 | $3.00 | $15.00 | ~10× |

For high-volume enrichment, **Flash is the sweet spot**. Flash-Lite is an option for further cost reduction at some accuracy tradeoff — worth piloting.

### Lever 5 — Prompt caching

For 150k-doc runs, the prompt scaffolding + dictionary list (~200–1,500 tokens) is reused across thousands of calls. **Enabling prompt caching cuts input cost by ~75%** on the cacheable prefix:

- 150k corpus saving on generation input: ~$1,500–2,000
- Requires switching from `google.generativeai` SDK to `google.genai` (already flagged as a migration in [TECHNICAL_ARCHITECTURE.md §12](TECHNICAL_ARCHITECTURE.md))

---

## 9. Optimized Production Cost — 150k Documents

Applying all production optimizations together:

| Optimization | Saving |
|---|---:|
| Baseline | $6,095 |
| Persist Phase 3.1 embeddings (Lever 2) | −$445 |
| 95% anchor rate at scale (Lever 1) | −$250 |
| Prompt caching on scaffolding + dictionary (Lever 5) | −$1,800 |
| **Optimized 150k corpus LLM spend** | **~$3,600** |

**Optimized per-document cost: ~$0.024** (2.4 cents per document).

---

## 10. What to Quote the Client

**Recommended quote bands** for a 150k-document engagement, accounting for variability:

| Scenario | LLM cost range |
|---|---:|
| **Conservative** (no optimizations, free-tier rate-limited) | **$6,000 – $8,000** |
| **Standard** (paid Vertex, anchor gate active) | **$5,000 – $6,500** |
| **Optimized** (all 5 levers applied) | **$3,000 – $4,500** |

**Add a 30–50% safety margin** for re-runs, QA passes, prompt iteration, and unforeseen quota spikes. A realistic budget line for **LLM spend at 150k scale: $7,500 – $10,000.**

This is **LLM API cost only** — does not include engineering, infrastructure, vector storage, editorial QA, or program management.

---

## 11. Where the Numbers Came From

| Number | Source |
|---|---|
| Chunk size (target 500w, hard cap 800w) | [src/semantic_chunker.py](src/semantic_chunker.py) |
| Per-call token estimates | Prompt templates in [src/phase3/providers.py](src/phase3/providers.py) |
| Anchor rate (84.6%) | POC run, [BEFORE_AFTER_DEMO.md §3](BEFORE_AFTER_DEMO.md) |
| L2 / L3 / L4 call counts | [TECHNICAL_ARCHITECTURE.md §11](TECHNICAL_ARCHITECTURE.md) |
| 974 chunks ÷ 127 L3 clusters | POC run metrics |
| Model pricing | Public Gemini API pricing (verify against Vertex contract rates) |

---

## 12. Quick Calculator (for ad-hoc estimates)

For any corpus, given:
- **N** = number of documents
- **C** = avg chunks per document (POC: ~22)
- **A** = anchor rate as decimal (POC: 0.85; projected at 150k: 0.95)

**Per-chunk LLM cost** (using public Gemini rates):
```
embed_cost  = 1800 × $0.15 / 1,000,000  = $0.00027
gen_input   = (1970 + (1-A) × 1375 + 5000/7.7) × $0.30 / 1,000,000
gen_output  = (275 + (1-A) × 45 + 45/7.7) × $2.50 / 1,000,000

total_per_chunk ≈ $0.0018 – $0.0022 depending on A
```

**Total corpus cost** = `N × C × total_per_chunk`

Plug in 150,000 × 22 × $0.00185 = **$6,105** baseline ✓

---

## 13. Bottom-Line Summary

| Scale | Chunks | Baseline LLM cost | Optimized LLM cost | Cost per doc |
|---|---:|---:|---:|---:|
| POC (44 docs) | 974 | **$1.80** | $1.20 | $0.04 |
| 10k docs | 220k | **$407** | $271 | $0.04 |
| 50k docs | 1.1M | **$2,035** | $1,355 | $0.04 |
| **150k docs** | **3.3M** | **$6,095** | **$3,600** | **$0.024–$0.041** |
| 500k docs | 11M | $20,317 | $12,000 | $0.024–$0.041 |

**Headline for the proposal:** *"Complete 4-level enrichment of a 150,000-document corpus costs roughly **$4,000–$6,000** in LLM inference — about **3–4 cents per document** — vs. an estimated $300,000+ for equivalent human editorial enrichment."*
