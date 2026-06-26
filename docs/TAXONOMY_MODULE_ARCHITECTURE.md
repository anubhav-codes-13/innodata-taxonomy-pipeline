# Taxonomy Module — Gap Analysis & Standalone Architecture

> **Goal:** Document *why* the current taxonomy is structurally wrong for a legal
> platform (Part 1), then carve taxonomy out into its own scalable module that
> fixes those problems and grows from **~40 files today to ~15,000 files** (Part 2).

---

# PART 1 — Legal Domain Taxonomy: Structure & Standards Gap Analysis

This part is grounded in the **actual pipeline output** — `KLI-JOIA-420501`
("State Immunity and the Recognition and Enforcement of ICSID Awards"),
`KLI-JOIA-420502`, and `enriched_dictionary.json`.

---

## Problem 1 — Wrong structural model: Tree instead of Facets (Highest Impact)

### What we have

A single hierarchical tree:

```
L1: International Arbitration
  └── L2: State Immunity
        └── L3: ICSID Waiver of Immunity
              └── L4: case_names, statutes, keywords
```

A document sits at **one path** through this tree.

### What the legal domain requires

A **faceted taxonomy** — four fully independent axes that classify the same
document simultaneously:

```
Practice Area   →  "International Arbitration"
Jurisdiction    →  "England & Wales", "United States", "ICSID"   ← MISSING
Document Type   →  "Journal Article", "Case Commentary"          ← ignored
Process/Matter  →  "Award Enforcement", "Annulment"              ← mixed into L2
```

### Evidence from our own output

`KLI-JOIA-420501` — the article about State Immunity — discusses:

- State immunity under **UK courts** (English SIA, section 9)
- State immunity under **US courts** (FSIA, section 1605)
- State immunity under **Australian courts** (HCA)
- State immunity under the **ICSID framework**

All of this is collapsed into `L2 = "State Immunity"`. A lawyer in a London firm
searching for *"State Immunity enforcement in UK courts"* gets the same results as
a US attorney researching FSIA. **The most important legal filter — jurisdiction —
does not exist in the taxonomy.**

Also, `KLI-JOIA-420502` is `doc_type: "commentary"` (a case note), but it sits
alongside `KLI-JOIA-420501` which is `doc_type: "essay"` (a journal article), under
the same L2 topics with no distinction. A junior associate who wants only
practitioner case notes cannot filter out academic essays.

---

## Problem 2 — Vocabulary explosion at L2: 50+ overlapping topics, no consolidation

### What we have in `enriched_dictionary.json`

The KA domain discovered **50+ L2 topics** beyond the 12 seeds. From the actual data:

```
"Appeals of Arbitral Awards":        8 chunks
"Judicial Review of Awards":         6 chunks
"Recourse Against Awards":           4 chunks
"Challenging Arbitral Awards":       1 chunk
"Award Setting Aside":               present in L3

"Mediation Law and Practice":        4 chunks
"Mediation Law":                     1 chunk
"Mediation Principles":              1 chunk
"Mediation Procedure":               1 chunk
"Mediation Procedures":              1 chunk
"Mediation Regulation":              1 chunk
```

These are **the same concept expressed 5–6 different ways**, because the LLM
generated a new topic each time rather than anchoring to an existing one. Without a
controlled legal vocabulary, the taxonomy sprawls.

### What SALI LMSS does instead

SALI defines **12 top-level Areas of Law** with stable URIs:

- `sali:ArbitrationMediation` — covers all of the above as one node
- `sali:InternationalArbitration` — sub-node, maps directly to the KA domain
- `sali:AwardEnforcement` — a **Process** facet, not mixed into the topic tree

The vocabulary is controlled by a consortium — you do not generate new nodes at
inference time.

---

## Problem 3 — Process/Matter mixed into Subject taxonomy at L2

### What we have

L2 topics mix two fundamentally different kinds of concept:

| Type | Examples in current L2 | Should be |
|------|------------------------|-----------|
| **Substantive law area** | "State Immunity", "Investment Arbitration" | Practice Area facet |
| **Procedural process** | "Award Enforcement", "Award Annulment", "Arbitration Procedure" | Process/Matter Type facet |

**These are not the same axis.** A document about *the procedure for enforcing an
award* (process) involving *state immunity law* (subject) needs both tags
independently — not as competing L2 options. Today it gets one or the other,
depending on which cosine similarity wins.

### SALI's solution

SALI separates these into distinct code sets:

- **Area of Law** (`sali:AreaOfLaw`) — substantive subject
- **Process** (`sali:Process`) — phase of legal work: Enforcement, Annulment, Negotiation…
- **Legal Entity** (`sali:LegalEntity`) — State, Individual, Corporation

Current L2 conflates all three.

---

## Problem 4 — L3 is generating noise and contradictions

### Evidence from the actual data

From `enriched_dictionary.json`, the top L3 sub-topic for KA is:

```
"Technological Due Process":  137 chunks
"Arbitral Award Enforcement":  91 chunks
```

**"Technological Due Process" appearing 137 times in an arbitration corpus is a red
flag** — the clustering algorithm grouped a large heterogeneous cluster and the
namer produced a generic label that does not reflect the content.

And from `final_enriched_documents.json` for `KLI-JOIA-420501`:

```json
"L3_Sub_Topics": [
  "ICSID Award Enforcement Immunity",
  "State Immunity Waiver",
  "Waiver State Immunity Enforcement"   ← same concept as the one above
]
```

Three L3 labels for one document, two meaning the same thing.

### Root cause

Unsupervised clustering with no legal-ontology anchor produces labels that are
**semantically equivalent from a legal standpoint but lexically different**. A
lawyer searching "State Immunity Waiver" will not find "Waiver State Immunity
Enforcement".

---

## Problem 5 — No citation normalization at L4

### Evidence from the output

`statutes_and_regulations` for `KLI-JOIA-420501` contains all of these as separate
entries:

```
"Article 54"
"Article 54(1)"
"Article 54 of the ICSID Convention"
"Article 54(1) of the ICSID Convention"
```

These all refer to the **same provision**. A search for "Article 54 ICSID" returns
different results from "Article 54(1) of the ICSID Convention" even though they
point to the same legal rule.

**This is the most critical L4 issue for a legal platform.** Legal citation
retrieval is exact — a lawyer searching for a specific provision needs all
documents citing it, regardless of how each author abbreviated it.

### What legal standards do

- **ECLI** (European Case Law Identifier) — canonical URI per case
- **Bluebook** normalization — standard citation forms
- **Neutral citation** (UK courts): `[2024] EWCA Civ 1257`

The pipeline extracts whatever form appears in the text. It needs a post-processing
step that normalizes variants to a canonical form.

---

## Problem 6 — No temporal dimension

Legal documents are time-sensitive in a way no other domain is. The law changes. A
2015 article on UK State Immunity may describe a different legal position than a
2025 article written after *Infrastructure Services (EWCA)*.

The taxonomy currently has:

- `publ_year: 2025` — at document level only
- No `law_as_at` date
- No `superseded_by` / `overruled_by` links

A lawyer asking *"what is the current UK position on state immunity waiver?"* needs
documents filtered to post-2024 UK jurisdiction — not all documents ever tagged
"State Immunity".

---

## What the structure should look like

### Current (hierarchical tree)

```json
{
  "L1_Domain": "International Arbitration",
  "L2_Primary_Topics": ["State Immunity", "Investment Arbitration"],
  "L3_Sub_Topics": ["ICSID Waiver of Immunity", "Waiver State Immunity Enforcement"],
  "L4_Entities": { }
}
```

### Target (faceted schema)

```json
{
  "practice_area":   "International Arbitration",        // SALI: sali:InternationalArbitration
  "sub_area":        "Investment Arbitration",           // SALI: sali:InvestmentArbitration
  "process":         "Award Enforcement",                // SALI: sali:AwardEnforcement (separate axis)
  "legal_concept":   ["State Immunity", "Waiver of Immunity"],  // controlled vocabulary
  "jurisdiction": {
    "primary":       "England and Wales",
    "secondary":     ["United States", "Australia", "ICSID"],
    "international_instrument": "ICSID Convention"
  },
  "doc_type":        "Journal Article",                  // from parsed doc_type
  "temporal": {
    "publ_year":     2025,
    "law_as_at":     "2025-10",
    "key_cases": [
      { "citation": "[2024] EWCA Civ 1257", "name": "Infrastructure Services (EWCA)" }
    ]
  },
  "entities": {
    "cases":         [{ "canonical": "[2024] EWCA Civ 1257", "short": "Infrastructure Services (EWCA)" }],
    "statutes":      [{ "canonical": "State Immunity Act 1978 (UK)", "sections": ["s.2", "s.9"] }],
    "organizations": ["English Court of Appeal", "ICSID"]
  }
}
```

### Mapping current layers to the target model

| Current | What it actually is | Target facet |
|---------|---------------------|--------------|
| L1 Domain | Practice area (broad) | `practice_area` |
| L2 Topic | Mix of subject + process | Split into `sub_area` + `process` (separate) |
| L3 Sub-topic | Unstable clustering label | Retire as a filter; keep as display-only |
| L4 entities | Case names, statutes, orgs | `entities.cases`, `entities.statutes`, `entities.organizations` |
| L4 keywords | Legal concepts | `legal_concept` (controlled vocab) |
| *(missing)* | — | `jurisdiction` |
| *(missing)* | — | `doc_type` (already in parser) |
| *(missing)* | — | `temporal.law_as_at` |

### Recommended standards to adopt

| Standard | What to adopt | Effort |
|----------|---------------|--------|
| **SALI LMSS** | Map `practice_area` + `process` to SALI URIs. Their `AreaOfLaw` code set covers KA and KCL exactly. | Low — a ~30-line mapping dict |
| **ECLI** | Add `ecli_id` to case entities for European court decisions | Medium — ECLI has a structured, regex-matchable format |
| **Neutral citation** | Normalize UK case citations `[YYYY] Court No` as canonical | Low — a citation normalizer post-step |
| **ISO 3166-1** | Use 2-letter country codes for jurisdiction values (not free text) | Low — a jurisdiction normalizer |

---

# PART 2 — The Taxonomy Module: Standalone, Scalable Architecture

## 1. The core reframe

Right now, "taxonomy" is **not a module**. It is smeared across the pipeline — a
bit in the router (L1+L2), a bit in the L4 extractor, a bit in the L3 clusterer, a
bit in synthesize. There is no single thing that *owns* classification.

The first architectural decision is to **carve taxonomy out into one module with
one job**:

- **Input:** a parsed document
- **Output:** stable, faceted tags (practice area, jurisdiction, process, doc type,
  concepts, normalized entities) — i.e. the **target faceted schema from Part 1**
- **Owns:** the controlled vocabulary and the rules for assigning it

Everything else (parsing, chunking, retrieval) talks to it through a clean
boundary. This matters for scale: a module with a clear boundary can be **batched,
parallelized, cached, and versioned independently** — a smeared pipeline cannot.

---

## 2. The 5 components inside the module

```
┌──────────────────────────────────────────────────────────────────────┐
│                        TAXONOMY MODULE                                 │
│                                                                        │
│   ┌────────────────────────────────────────────────────────────┐    │
│   │  1. VOCABULARY AUTHORITY  (the source of truth)             │    │
│   │                                                              │    │
│   │  The approved, controlled list of every tag that can exist: │    │
│   │   • Practice Areas    (12 + curated)                        │    │
│   │   • Sub-Areas                                               │    │
│   │   • Processes         (Enforcement, Annulment...)           │    │
│   │   • Jurisdictions     (UK, US, ICSID — ISO codes)           │    │
│   │   • Legal Concepts                                          │    │
│   │   • L3 sub-topics     (curated, NOT clustered)              │    │
│   │                                                              │    │
│   │  • Mapped to SALI standard URIs                             │    │
│   │  • VERSIONED: v1, v2... frozen between releases             │    │
│   │  • This is the ONLY place new tags are born                 │    │
│   └────────────────────────────────────────────────────────────┘    │
│            │ reads from                       │ proposes to            │
│            ▼                                   ▲                        │
│   ┌─────────────────────────┐     ┌──────────────────────────────┐   │
│   │  2. CLASSIFIER          │     │  4. GOVERNANCE LOOP          │   │
│   │  (the tagger)           │     │  (vocabulary evolution)      │   │
│   │                         │     │                              │   │
│   │  Per chunk, assigns     │     │  Collects "I saw something   │   │
│   │  facets by MATCHING     │     │  new" proposals from the     │   │
│   │  against the Authority  │     │  classifier → batches them   │   │
│   │  on FOUR axes:          │     │  → human/batch review →      │   │
│   │   practice area,        │     │  → promotes approved terms   │   │
│   │   jurisdiction,         │     │    into the next vocab       │   │
│   │   process, doc type     │     │    version                   │   │
│   │                         │     │                              │   │
│   │  • Cheap path: embed +  │     │  Closes the broken feedback  │   │
│   │    cosine match (95%)   │     │  loop we found (Problem 2)   │   │
│   │  • Expensive path: LLM  │     └──────────────────────────────┘   │
│   │    PROPOSES (does NOT   │                                         │
│   │    auto-add) (5%)       │                                         │
│   └─────────────────────────┘                                         │
│            │                                                            │
│            ▼                                                            │
│   ┌─────────────────────────┐                                         │
│   │  3. ENTITY NORMALIZER   │                                         │
│   │                         │                                         │
│   │  Extracts + canonical-  │                                         │
│   │  izes cases, statutes,  │                                         │
│   │  citations (Problem 5)  │                                         │
│   │  "Article 54" variants  │                                         │
│   │   → one canonical form  │                                         │
│   └─────────────────────────┘                                         │
│            │                                                            │
│            ▼                                                            │
│   ┌────────────────────────────────────────────────────────────┐    │
│   │  5. TAXONOMY STORE                                          │    │
│   │  Stable faceted tags, with version stamp, queryable         │    │
│   └────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 3. How each component solves a problem from Part 1

| Component | Problem it fixes | In simple terms |
|-----------|------------------|-----------------|
| **1. Vocabulary Authority** | P2 (vocab explosion), P4 (L3 instability), P3 (process/subject mix) | One approved list. Nothing gets tagged with a word that isn't on the list. Like a library that only uses official subject headings. |
| **2. Classifier** | P1 (tree → facets), P3 (separate process axis), "AI invents names" | Tags the document on 4 independent axes at once, by **picking from the approved list**, not inventing. |
| **3. Entity Normalizer** | P5 (citation duplication) | Collapses every way of writing the same case/statute into one canonical form. |
| **4. Governance Loop** | P2 (broken feedback loop), non-reproducible taxonomy | New concepts go to a **review queue**, not straight into the live taxonomy. A human approves them into the next version. |
| **5. Taxonomy Store** | No vector store; trapped JSON | Tags stored in a form you can actually filter and search (enables the faceted queries P1 needs). |
| *(temporal facet on output)* | P6 (no time dimension) | `temporal.law_as_at` carried as a first-class facet. |

---

## 4. The central insight for scale (40 → 15,000)

> **The anchor/expand pattern already in the router is exactly right for scale —
> but only if the vocabulary is allowed to mature and then freeze.**

```
TODAY (broken — this IS Problem 2):
  Doc 1    → no vocab match → AI invents "Mediation Law"        (LLM call $)
  Doc 50   → no vocab match → AI invents "Mediation Practice"   (LLM call $)  ← duplicate!
  Doc 500  → no vocab match → AI invents "Mediation Procedure"  (LLM call $)  ← duplicate!
  ...the vocabulary never freezes, so you pay for an LLM call FOREVER,
     and you generate a new duplicate every time.

TARGET (matured + frozen):
  Doc 1-200    → DISCOVERY phase: AI proposes freely, human curates a clean v1
  Doc 201      → "Mediation" already in vocab → cheap cosine match  (no LLM)
  Doc 5,000    → cheap cosine match  (no LLM)
  Doc 15,000   → cheap cosine match  (no LLM)
  ...only a genuinely novel concept (~1 in 50 docs) triggers the LLM.
```

At 40 documents everything is "expand" because the vocabulary is immature. At
15,000 documents, with a mature frozen vocabulary, **95%+ of classification is a
cheap embedding lookup with no LLM call at all.**

**Scale is not about a bigger machine — it is about driving the vocabulary to
maturity, then freezing it.**

---

## 5. What physically breaks at 15K, and the architectural answer

| What breaks at 15K files | Why | Architectural fix |
|--------------------------|-----|-------------------|
| **Sequential processing** | ~40 docs ≈ 15 min → 15K ≈ **~4 days** single-threaded | Concurrent workers + batch embedding API. Docs are independent → embarrassingly parallel. |
| **L3 clustering** | AgglomerativeClustering needs an N×N matrix. 15K docs ≈ 300K+ chunks → **90 billion-cell matrix → impossible** | **Delete clustering** (also fixes Problem 4). Replace with classification against a curated L3 sub-vocabulary. Stable AND scalable. |
| **Vocabulary explosion** | 40 docs already gave 50+ topics; 15K → **thousands of duplicates** (Problem 2 at scale) | Governance Loop + frozen versioned vocabulary. |
| **Re-embedding twice** | Doubling embedding cost across 300K chunks = real money | Compute each chunk embedding **once**, persist, reuse. |
| **Flat JSON output** | 300K chunks of JSON = **gigabytes you can't query** | Taxonomy Store backed by a real index, not files. |
| **Full re-runs** | Doc #15,001 arrives → don't reprocess 15,000 | **Incremental ingestion** — process only new/changed docs. Frozen vocab makes tags stable across runs. |
| **Cost / rate limits** | 300K LLM calls hits quota walls | Anchor-first design (95% no LLM) + batching + checkpointing + retry. |

---

## 6. The scale journey is two phases, not one jump

```
┌─────────────────────────────────────────────────────────────┐
│  PHASE A — VOCABULARY DISCOVERY   (first ~200–500 docs)     │
│                                                             │
│  Goal: build a clean, curated v1 vocabulary.               │
│  • Let the classifier propose freely (lots of LLM calls)   │
│  • Governance Loop collects every proposal                 │
│  • Human reviews, dedupes, maps to SALI → freezes v1       │
│  • Expensive per-doc, but you only do it once              │
└─────────────────────────────────────────────────────────────┘
                          │  freeze v1
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  PHASE B — VOCABULARY APPLICATION   (scale to 15,000)       │
│                                                             │
│  Goal: tag at volume, cheaply.                             │
│  • Vocabulary frozen → 95% cheap cosine matches            │
│  • Concurrent workers, batched embeddings                  │
│  • Only rare novel concepts go to the review queue         │
│  • Periodically (e.g. every 2K docs) review the queue →    │
│    release v2 → re-tag only affected docs                  │
└─────────────────────────────────────────────────────────────┘
```

You are at the very start of Phase A today. The architectural work is building the
Vocabulary Authority + Governance Loop so you can *finish* Phase A deliberately;
then Phase B scales almost for free.

---

## 7. The clean module boundary (what goes in, what comes out)

```
   PARSED DOCUMENT                          FACETED TAGS (versioned)
   ───────────────                          ────────────────────────
   doc_id, doc_type                         practice_area    (+ SALI URI)
   sections, paragraphs        TAXONOMY     sub_area
   editorial topics      ───►  MODULE  ───► process          ← separate axis (P3)
   cust_groups                              jurisdiction[]    ← NEW axis (P1)
   case_metadata                            legal_concept[]
                                            doc_type          ← surfaced (P1)
                                            temporal.law_as_at ← NEW (P6)
                                            entities (normalized, P5)
                                            vocab_version: "v3"
                          ▲           │
                          │           ▼
                   VOCABULARY    REVIEW QUEUE
                   AUTHORITY     (new term proposals
                   (versioned)    for human approval)
```

Two things cross the boundary that do not exist today:

- **`vocab_version` stamp** on every tag — so you always know *which version of the
  truth* tagged this document. Essential at 15K when the vocabulary evolves.
- **A review queue coming back out** — the module does not silently mutate its own
  truth; it proposes, and governance decides.

---

## 8. The 4 architectural moves, in priority order

1. **Build the Vocabulary Authority as a real, versioned, owned artifact**
   (today it is a half-used `master_dictionary.json`). The spine — everything hangs
   off it. *Fixes P2, P3, P4 at the root.*
2. **Make the Classifier multi-facet and match-only** (propose, never auto-add).
   *Fixes P1 (tree → facets) and the duplicate explosion in one move.*
3. **Delete L3 clustering, replace with curated-vocabulary classification.**
   *Fixes P4 and unblocks 15K scale — clustering cannot run at that size.*
4. **Add the Governance Loop + version stamping.** Lets the vocabulary mature and
   freeze — what makes 95% of classification cheap and the system affordable at volume.

---

## Appendix — Mapping to current code

| Current file | Role today | Becomes (in the module) |
|--------------|------------|--------------------------|
| `src/tag_harvester.py` + `data/phase3/seed_topics.json` | Half-used dictionary builder | **Vocabulary Authority** (versioned, SALI-mapped) |
| `src/phase3/router.py` (L1+L2) | Single-axis anchor/expand | **Classifier** (multi-facet, match-only) |
| `src/phase3/l4_extractor.py` | Entity + keyword extraction | **Entity Normalizer** (+ canonicalization) |
| `src/phase3/l3_discovery.py` | Unsupervised clustering | **Deleted** → curated L3 classification |
| `src/phase4/expand_dictionary.py` | Collects discovered terms (dead-ends) | **Governance Loop** (feeds review → next vocab version) |
| `src/phase4/synthesize.py` | Rolls chunk tags up to doc level | Feeds the **Taxonomy Store** |
