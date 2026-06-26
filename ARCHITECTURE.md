# Architecture — Wolters Kluwer KA/KCL Enrichment Pipeline

**Goal.** Turn Kluwer Law International (KLI) KEA-BASIC XML documents — journal articles, book chapters, case-notes, and legislation — into an LLM/RAG-ready knowledge base with a 4-level taxonomy (L1–L4) and a document-relationship graph.

**Scope in this POC.**
- KA (Kluwer Arbitration, 23-file sample) and KCL (Kluwer Competition Law, 21-file sample)
- Two corpora, same DTD, disjoint taxonomies, one pipeline
- Every step is demonstrable on the sample, parameterised for full-corpus runs without code changes.

---

## Pipeline flow

```
                                 ┌─────────────────────────┐
                                 │  KA-xml-samples/*.xml   │
                                 │  KCL-xml-samples/*.xml  │
                                 └────────────┬────────────┘
                                              │
                                              ▼
               ┌─────────────────────────────────────────────────────────┐
 PHASE 1       │  src/rag_parser.py                                      │
 PARSE         │  KLI KEA-BASIC XML → clean JSON (5 doc types)           │
               │  Pre-processing:                                         │
               │   · strip DOCTYPE + internal subsets (entity refs)       │
               │   · strip XML comments (legacy <frontmatter> duplicates) │
               │   · strip <?page …?> processing instructions             │
               │  Produces: parsed_docs.json                              │
               └────────────┬────────────────────────────────────────────┘
                            │
                            ▼
               ┌─────────────────────────────────────────────────────────┐
 PHASE 2       │  src/semantic_chunker.py    Paragraph Group Chunking    │
 CHUNK +       │     + Prefix-Fusion lineage breadcrumb                   │
 HARVEST       │  src/tag_harvester.py       Domain-partitioned master   │
               │     dictionary (seed taxonomy merge, pristine mode)      │
               │  src/relationship_extractor.py   xref → graph edges     │
               │  Produces: chunked_docs.json, master_dictionary.json,   │
               │            relationship_graph.json                       │
               └────────────┬────────────────────────────────────────────┘
                            │
                            ▼
               ┌─────────────────────────────────────────────────────────┐
 PHASE 3       │  src/phase3/router.py       L1 domain + L2 anchor/expand │
 ENRICH        │  src/phase3/l3_discovery.py Cluster-then-Label on L2    │
 (L1-L4)       │  src/phase3/l4_extractor.py Case/statute/org + keyword  │
               │  All nodes share providers in src/phase3/providers.py:  │
               │   · Embedder, TopicGenerator, SubTopicNamer,            │
               │     EntityExtractor  (protocols)                         │
               │   · Gemini + Vertex + Dummy implementations             │
               │  Produces: enriched_chunks.json                          │
               └────────────┬────────────────────────────────────────────┘
                            │
                            ▼
               ┌─────────────────────────────────────────────────────────┐
 PHASE 4       │  src/phase4/synthesize.py                               │
 ROLL UP       │  Chunk-level L1/L2/L3/L4 → document-level taxonomy      │
               │  + L2_Provenance (% Anchored vs Expanded)               │
               │  + --compare <doc_id> Before/After visualizer           │
               │  Produces: final_enriched_documents.json                 │
               └─────────────────────────────────────────────────────────┘
```

---

## The 4-level taxonomy

The conceptual core of the pipeline. Every chunk — and, rolled up, every document — gets four labels:

| Level | Name | What it is | Example (KA) | Example (KCL) |
|---|---|---|---|---|
| **L1** | Domain | Product line / practice area | `International Arbitration` | `Competition Law` |
| **L2** | Macro-Topic | 2–4 word broad subject | `State Immunity` | `Merger Control` |
| **L3** | Sub-Topic | 2–4 word specific concept derived from clustering | `ICSID Immunity Waiver` | `Transaction Notification Scope` |
| **L4** | Entities + Keywords | Case names, statutes, organisations, specific concepts | `Infrastructure Services (EWCA)`; `State Immunity Act § 9` | `Article 22 EUMR`; `Illumina/GRAIL transaction` |

L1 is derived structurally from `cust_groups`. L2 goes through an anchor-or-expand routing gate (below). L3 is unsupervised clustering inside each L2 group, labelled by Gemini after the fact. L4 is Gemini-driven NER+keyword extraction with post-call dictionary validation.

### Routing gate (anchor vs expand)

This is the main cost-saving design. For each chunk and its L1 domain:

1. **Embed** the chunk's `fused_text` once with Gemini's `gemini-embedding-001` (3072-d) or `BAAI/bge-small-en-v1.5` (384-d).
2. **Embed all L2 anchor topics** in the master dictionary once (cached across the batch).
3. **Max cosine** chunk-vs-anchors.
4. If `>= recommended_anchor_threshold` → **ANCHOR**. Assign the matched L2 verbatim. No LLM call.
5. Otherwise → **EXPAND**. Call Gemini 2.5 Flash to propose a new 2–4 word L2.

Thresholds are per embedder (see `recommended_anchor_threshold` on each class): bge-small 0.85, gemini 0.75, dummy 0.30. The router auto-picks from the embedder it was constructed with — no magic numbers in calling code.

Phase 4 surfaces `L2_Provenance` on each synthesized document so the ratio is visible:

```json
"L2_Provenance": {
  "summary": "Mixed: 66.7% Anchored, 33.3% Expanded",
  "anchored_count": 2, "expanded_count": 1, "total": 3,
  "anchored_pct": 66.7, "expanded_pct": 33.3
}
```

On the current 18-chunk demo batch, **~79% of documents route entirely through the cheap anchor path** — exactly the efficiency story the gate is designed to produce.

---

## Module map

Everything is under `src/`. Each module is independently runnable and emits its own JSON artefact; downstream modules consume those artefacts. No hidden cross-module state.

### Parsing & EDA

| File | Role |
|---|---|
| [src/rag_parser.py](src/rag_parser.py) | XML → `parsed_docs.json`. Handles 5 doc types: `essay`, `legislation`, `commentary`, `caselaw`, `booktoc`. Emits `metadata`, `enrichment`, `case_metadata`, `body.sections[].paragraphs`, `edges.xrefs`. |
| [src/ka_parser/](src/ka_parser/) | Earlier EDA-focused parser kept for the EDA reports. Produces the `data/ka_eda` / `data/kcl_eda` findings docs. |

### Phase 2 — chunk and harvest

| File | Role |
|---|---|
| [src/semantic_chunker.py](src/semantic_chunker.py) | Paragraph Group Chunking (target 500 words, slack 150, hard cap 800) + Prefix-Fusion breadcrumb `[Container: … │ Document: … │ Section: id - title]`. Strips `<note>` footnotes from chunk text. |
| [src/tag_harvester.py](src/tag_harvester.py) | Consolidates existing topics/keywords/entities into `master_dictionary.json`, partitioned by domain (`KA`, `KCL`). Seed-taxonomy merge via `--seed-topics`. Pristine mode via `--drop-harvested-topics`. |
| [src/relationship_extractor.py](src/relationship_extractor.py) | Walks `edges.xrefs` in parsed docs → flat directed-edge list. Filters external URLs by default. Recognises `type="url"` even when scheme is missing. |

### Phase 3 — L1–L4 enrichment

| File | Role |
|---|---|
| [src/phase3/router.py](src/phase3/router.py) | `TopicRouter`. L1 from `cust_groups`. L2 anchor-or-expand. Auto-threshold from embedder. Cached anchor embeddings per L1. |
| [src/phase3/l4_extractor.py](src/phase3/l4_extractor.py) | `L4ExtractionNode`. Gemini structured-JSON call per chunk. Post-call validator: paraphrased "matches" demoted from `existing_matched_keywords` → `new_extracted_keywords`. |
| [src/phase3/l3_discovery.py](src/phase3/l3_discovery.py) | Group-by-L2 → AgglomerativeClustering (cosine, distance threshold) → top-K centroid chunks → Gemini names the cluster. Small clusters collapse into `General {L2_Topic}`. |
| [src/phase3/providers.py](src/phase3/providers.py) | All external-model plumbing. Protocols: `Embedder`, `TopicGenerator`, `EntityExtractor`, `SubTopicNamer`. Implementations: Google GenAI SDK, Vertex AI SDK, Dummies, Sentence-Transformers. Loads `.env` at import. |
| [src/phase3/run_demo.py](src/phase3/run_demo.py), [run_l3_demo.py](src/phase3/run_l3_demo.py), [run_l4_demo.py](src/phase3/run_l4_demo.py) | Per-node CLI smoke-tests with stratified KA/KCL sampling and human-readable logging. |

### Phase 4 — document synthesis

| File | Role |
|---|---|
| [src/phase4/synthesize.py](src/phase4/synthesize.py) | Group chunks by `doc_id`. Produces `L1_Domain`, `L2_Primary_Topics` (top 1–2), `L2_All_Topics`, `L2_Provenance`, `L3_Sub_Topics`, `L4_Entities`, `L4_Keywords`. Carries `case_metadata` for caselaw / commentary. `--compare <doc_id>` prints Before/After side-by-side. |

---

## Data artefacts

One source of truth per phase. All under `data/`.

```
data/
├── ka_eda/
│   ├── parsed_docs.json                (Phase 1 EDA output)
│   └── FINDINGS.md                     (schema / coverage / data-quality findings)
├── kcl_eda/
│   ├── parsed_docs.json
│   └── FINDINGS.md
├── rag_out/
│   ├── ka_parsed.json                  (Phase 1)
│   ├── kcl_parsed.json
│   ├── ka_chunks.json                  (Phase 2)
│   ├── kcl_chunks.json
│   ├── master_dictionary.json          (Phase 2 – harvested + seed taxonomy)
│   └── relationship_graph.json         (Phase 2 – xref edges)
├── phase3/
│   ├── seed_topics.json                (12 KA + 12 KCL curated L2 anchors)
│   ├── routed_*.json                   (Phase 3.1 outputs)
│   ├── l3_*.json                       (Phase 3.3 outputs)
│   └── l4_*.json                       (Phase 3.2 outputs)
└── phase4/
    ├── enriched_chunks.json            (Phase 4 input — chunks with L1–L4)
    └── final_enriched_documents.json   (Phase 4 output — doc-level rollup)
```

### Chunk record (post Phase 3)

```json
{
  "doc_id":            "KLI-JOIA-420502",
  "doc_type":          "commentary",
  "cust_groups":       ["CH", "KA"],
  "section_id":        "S0001",
  "chunk_id":          "S0001_chunk_1",
  "fused_text":        "[Container: … | Document: … | Section: S0001 - …]\n\n<body text>",
  "inherited_topics":  ["International Commercial Arbitration", "..."],
  "inherited_keywords":["Arbitrator Bias", "Issue Conflict", "..."],

  "L1_Domain":         "International Arbitration",
  "L2_Topic":          "Arbitrator Independence",
  "L2_Source":         "anchor",
  "L2_Similarity":     0.795,

  "L3_Sub_Topic":      "Arbitrator Issue Conflict",
  "L3_Source":         "namer",

  "L4_metadata": {
    "entities": {
      "case_names":               ["DJP v. DJO", "Halliburton Company v. Chubb Bermuda"],
      "statutes_and_regulations": [],
      "organizations":            ["Singapore Court of Appeal"]
    },
    "keywords": {
      "existing_matched_keywords": ["Arbitrator Bias", "Issue Conflict"],
      "new_extracted_keywords":    ["Prejudgment"]
    }
  }
}
```

### Document record (Phase 4 output)

```json
{
  "doc_id":          "KLI-JOIA-420502",
  "doc_type":        "commentary",
  "container_title": "Journal of International Arbitration",
  "publ_year":       2025,
  "cust_groups":     ["CH", "KA"],
  "case_metadata": {
    "court":        "Singapore Court of Appeal",
    "case_name":    "DJP and others v. DJO [2024] SGHC(I) 24",
    "case_number":  "Court of Appeal / Civil Appeal No 6 of 2024",
    "decision_date":"20250408",
    "parties": [
      {"role": "Appellant",  "name": "DJP"},
      {"role": "Respondent", "name": "DJO"}
    ]
  },
  "taxonomy": {
    "L1_Domain":         "International Arbitration",
    "L2_Primary_Topics": [{"l2_topic": "Arbitrator Independence", "chunk_count": 2}],
    "L2_All_Topics":     [{"l2_topic": "Arbitrator Independence", "chunk_count": 2}],
    "L2_Provenance":     {"summary": "100% Anchored", "anchored_count": 2, "expanded_count": 0, "...": "..."},
    "L3_Sub_Topics":     ["Arbitrator Issue Conflict"],
    "L4_Entities":       {"case_names": ["..."], "statutes_and_regulations": ["..."], "organizations": ["..."]},
    "L4_Keywords":       {"all": ["..."], "matched_from_dictionary": ["..."], "newly_extracted": ["..."]}
  },
  "chunk_count": 2
}
```

---

## Design decisions worth calling out

### XML pre-processing is not optional
The KEA-BASIC DTD ships with three landmines that crash stock `xml.etree`:
- **DOCTYPE with internal subset** (`[ <!ENTITY SLSD_…_gif …> ]`) declaring binary entities
- **Legacy commented-out `<frontmatter>`** — 56% of KA / 86% of KCL files carry a historical snapshot
- **`<?page nr="…"?>` processing instructions** — duplicate whitespace on text flattening

All three are stripped in `src.rag_parser.preprocess()` before `ET.fromstring()`. Without this, ~5% of files fail to parse outright and the rest contain duplicated bibliographic metadata.

### Five document shapes, one output schema
`essay`, `legislation`, `commentary`, `caselaw`, `booktoc` live under different body wrappers (`<text>`, `<legis-text>`, `<juris-text>`, `<juris-comment>` / `<legis-comment>`, `<booktoc-text>`). The parser normalises all of them into the same output shape. `case_metadata` is present only on caselaw + commentary, `null` otherwise — keeping a single schema simplifies every downstream consumer.

### Chunking respects structure, not character count
Paragraph Group Chunking with target 500 words, slack 150, hard cap 800. Never splits mid-paragraph unless a single paragraph exceeds the hard cap (fallback order: sentences → newlines → word boundaries, never mid-token). Every chunk carries a Prefix-Fusion breadcrumb so retrieval has the container/document/section lineage inside the embedded string itself.

### Taxonomy is partitioned by domain
`master_dictionary.json` has separate `KA` and `KCL` blocks — arbitration and competition-law topics never mix. Universal entities (countries, organisations) stay global. Two modes:
- **Merge mode** (default with `--seed-topics`): seed taxonomy + editorial XML topics coexist. Seed IDs/texts win on conflict.
- **Pristine mode** (`--drop-harvested-topics`): only curated seeds; editorial XML topics dropped. Gives the router a clean ground-truth anchor set. This is the mode used for the POC demo.

### Self-calibrated anchoring threshold
Every embedder class advertises its own `recommended_anchor_threshold`. The router calls `_auto_threshold(embedder)` when none is specified, so switching from bge-small to Gemini to Dummy picks the right cosine cutoff automatically:
- `SentenceTransformerEmbedder` (bge-small): **0.85**
- `GeminiEmbedder` (gemini-embedding-001): **0.75** (empirical — Gemini vectors peak lower than bge-small)
- `DummyEmbedder`: **0.30**

Override via `anchor_threshold=` (library) or `--threshold` (CLI). No hardcoded magic numbers in calling code.

### L4 keyword dictionary is defended post-call
Gemini is asked to echo dictionary keywords verbatim when a chunk matches one. Sometimes it paraphrases. `_validate_matched_keywords()` in `l4_extractor.py` scans `existing_matched_keywords` against the real dictionary and demotes anything that isn't a literal match into `new_extracted_keywords`. The controlled-vocabulary guarantee does not depend on the model obeying instructions.

### Cluster-then-Label for L3
Rather than ask the LLM to invent L3s directly (expensive, inconsistent across batches), the L3 node embeds each L2 group, clusters by AgglomerativeClustering with cosine, picks 3–5 centroid chunks per cluster, and asks Gemini to name the cluster *after* seeing the centroids. Small clusters (< `min_cluster_size`) collapse into `General {L2_Topic}` — mirrors HDBSCAN's noise handling while staying on sklearn (already a project dep).

### Chunk-level cost and audit trail
Every enrichment step records its decision:
- `L2_Source` ∈ {`anchor`, `generator`, `generator_error`}
- `L3_Source` ∈ {`namer`, `noise`, `namer_error`}
- `L2_Similarity` (cosine against the winning anchor)
- `L4_metadata.keywords.{existing_matched, new_extracted}` separation

Phase 4 rolls these into `L2_Provenance` so anyone reading the final JSON can see whether a doc hit the cheap path or required a generator call.

---

## How to run

```
python -m pip install -r requirements.txt
echo "GOOGLE_API_KEY=..." > .env      # .env is auto-loaded by src/phase3/providers.py
```

### Full pipeline on the sample corpora

```bash
# --- Phase 1: parse ---
python -m src.rag_parser KA-xml-samples/KA-xml-samples   --out data/rag_out/ka_parsed.json
python -m src.rag_parser KCL-xml-samples/KCL-xml-samples --out data/rag_out/kcl_parsed.json

# --- Phase 2: chunk + harvest + graph ---
python -m src.semantic_chunker data/rag_out/ka_parsed.json  --out data/rag_out/ka_chunks.json
python -m src.semantic_chunker data/rag_out/kcl_parsed.json --out data/rag_out/kcl_chunks.json

python -m src.tag_harvester \
    data/rag_out/ka_parsed.json data/rag_out/kcl_parsed.json \
    --seed-topics data/phase3/seed_topics.json --drop-harvested-topics \
    --out data/rag_out/master_dictionary.json

python -m src.relationship_extractor \
    data/rag_out/ka_parsed.json data/rag_out/kcl_parsed.json \
    --out data/rag_out/relationship_graph.json

# --- Phase 3: route + L4 + L3 ---
python -m src.phase3.run_demo \
    --chunks data/rag_out/ka_chunks.json data/rag_out/kcl_chunks.json \
    --master data/rag_out/master_dictionary.json \
    --sample 12 --embedder gemini --generator google \
    --out data/phase3/routed.json

python -m src.phase3.run_l4_demo \
    --chunks data/phase3/routed.json \
    --master data/rag_out/master_dictionary.json \
    --extractor google \
    --out data/phase3/routed_l4.json

# L3 is applied per-L2. run_l3_demo picks the largest populated L2 group;
# for every-L2 processing, call discover_l3_for_l2() in a loop (see
# "Known gaps" below — the --all-l2 flag is a planned convenience).

# --- Phase 4: synthesize ---
python -m src.phase4.synthesize \
    --chunks data/phase4/enriched_chunks.json \
    --parsed data/rag_out/ka_parsed.json data/rag_out/kcl_parsed.json \
    --out    data/phase4/final_enriched_documents.json \
    --compare KLI-JOIA-420502
```

### Provider options

All Phase 3 CLIs accept `--embedder`, `--generator`, `--extractor`, `--namer` with these values:
- `gemini` — Gemini 2.5 Flash via `google.generativeai`. Default when `.env` has `GOOGLE_API_KEY`.
- `vertex` — Vertex AI SDK. Needs `GOOGLE_CLOUD_PROJECT` + ADC.
- `sentence-transformers` (embedder only) — local `BAAI/bge-small-en-v1.5`. No API key, pulls ~2 GB of torch on first install.
- `dummy` — zero-dependency placeholders for smoke tests.

---

## What's delivered vs what's next

### Delivered (current repo state)

| Phase | Module | Smoke-tested on |
|---|---|---|
| 1 | `rag_parser.py` | 23 KA + 21 KCL = 44 docs |
| 2 | `semantic_chunker.py` | 428 KA chunks + 546 KCL chunks, body word counts 14–799 (all below 800 soft cap) |
| 2 | `tag_harvester.py` | 12+12 curated seeds (pristine) + harvested editorial tags merged |
| 2 | `relationship_extractor.py` | 56 internal edges (27 resolve within corpus) |
| 3.1 | `router.py` + `providers.py` | 12-chunk batch on Gemini 2.5 Flash, 10/12 anchored against seeds |
| 3.2 | `l4_extractor.py` | 18-chunk batch, 100% extraction success, dictionary-match validator passes |
| 3.3 | `l3_discovery.py` | Cluster-then-label across all L2 groups of enriched batch |
| 4 | `synthesize.py` | 14 synthesized docs, Before/After comparison, L2_Provenance rollup |

### Known gaps / future work

| Item | Where | Notes |
|---|---|---|
| **`google.generativeai` SDK deprecated** | `src/phase3/providers.py` | Google has ended support in favour of `google.genai`. Works today but should migrate before production. |
| **L4 case-insensitive dedup** | `l4_extractor.py._merge_l4` | Extractor occasionally returns `"Singapore Court of Appeal"` and `"Singapore Court Of Appeal"` as separate orgs. Casefold-dedup in the merge step is the fix. |
| **Batch L3 CLI flag** | `run_l3_demo.py` | Today processes one L2 group per invocation. A `--all-l2` flag calling `discover_l3_for_l2` in a loop would finish a batch in one command. |
| **Quota headroom** | any Gemini call | Current `GOOGLE_API_KEY` uses free-tier quotas; `gemini-embedding-001` rate-limits after a few seconds of sequential calls. Exponential backoff is implemented (4 retries) but for bigger batches, move to Vertex AI or a paid key. |
| **Full-corpus scale** | whole pipeline | Tested on 44 docs. Chunk record is self-contained; the pipeline parallelises trivially at the chunk level. No structural changes needed for the full KA/KCL corpora; just more API budget. |
| **Formal tests** | new | No pytest suite yet. EDA and smoke tests live inside the CLIs. Adding `pytest` + a few representative fixtures is worthwhile before the first non-POC release. |
| **Recursive section chunking** | `semantic_chunker.py` | Current chunker flattens past top-level sections. Most docs (KA up to depth 3, KCL up to depth 4) have nested sections that would chunk more semantically with recursive descent. A refinement, not a correctness fix. |

---

## Observations from the sample data

These are the findings that shaped the design. Full numbers live in [data/ka_eda/FINDINGS.md](data/ka_eda/FINDINGS.md) and [data/kcl_eda/FINDINGS.md](data/kcl_eda/FINDINGS.md).

- **KA and KCL have inverted enrichment profiles.** KA has 22% keyword coverage but only 4% topic coverage; KCL has 4% keyword coverage but 57% topic coverage. The pipeline must treat both as first-class — you can't assume either layer is populated.
- **KCL topics are ID-coded** (`KCL-001`…`KCL-005`) with no collisions, suggesting an internal editorial taxonomy we don't have direct access to. The pristine seed dictionary approximates this.
- **5 doc types, not 3.** Initial EDA expected essay + legislation + booktoc. Commentary (`<juris-comment>` / `<legis-comment>`) and caselaw (`<juris>` + `<juris-description>`) are distinct shapes carrying structured case metadata (parties, court, date, case number). The parser handles all five uniformly.
- **Document length is bimodal.** ~25% of KCL docs are <2k words (MTM country reports, EU snippets, book annexes) and a long tail of 20k–50k word chapters. Chunking must adapt; a fixed-size window would destroy retrieval quality at both ends.
