# 8-Week Implementation Plan — Insight Engine Production Deployment

End-to-end delivery plan for enriching a **150,000-document legal/regulatory corpus** with the Insight Engine 4-level taxonomy. Includes SME (Subject Matter Expert) review checkpoints, QA gates, and parallel-track execution.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Assumptions & Prerequisites](#2-assumptions--prerequisites)
3. [Team Structure & Roles](#3-team-structure--roles)
4. [Week-by-Week Plan](#4-week-by-week-plan)
5. [SME Review Cadence](#5-sme-review-cadence)
6. [Milestones & Deliverables](#6-milestones--deliverables)
7. [Risk Register](#7-risk-register)
8. [Success Metrics](#8-success-metrics)
9. [Post-Deployment Handover](#9-post-deployment-handover)

---

## 1. Executive Summary

**Objective:** Enrich 150,000 raw XML documents with a complete 4-level taxonomy (L1 Domain → L2 Macro-Topic → L3 Sub-Topic → L4 Entities + Keywords) in 8 weeks, with SME-validated output quality at every stage.

**Approach:** Phased rollout — pilot validation → controlled scaling → full production run → handover. Each phase ends with an SME quality gate.

**Headline timeline:**
- **Weeks 1–2:** Discovery, setup, seed dictionary
- **Weeks 3–4:** Pilot (5k docs) + SME review cycle 1
- **Weeks 5–6:** Full production run (150k docs) + parallel SME review cycle 2
- **Weeks 7–8:** Final QA, dictionary refinement, delivery & handover

**Effort estimate:** ~3.5 FTEs (engineering) + ~2 SMEs (legal/domain) + 1 PM, sustained across 8 weeks.

---

## 2. Assumptions & Prerequisites

Before Week 1 kicks off, the following must be in place:

| # | Prerequisite | Owner | Status check |
|---|---|---|---|
| 1 | Source XML corpus access (150k documents) | Client | Sample subset shared in advance |
| 2 | XML schema documentation (DTD / XSD) | Client | One-page schema summary |
| 3 | LLM provider account (Vertex AI / Gemini API) with quota | Innodata + Client | Quota approved for ~10B tokens |
| 4 | Client editorial team allocated for SME reviews | Client | 2 SMEs × ~6 hours/week confirmed |
| 5 | Existing editorial taxonomy / seed topics (if any) | Client | Provided as JSON or spreadsheet |
| 6 | Output target system (vector DB, search index, knowledge graph) | Client | Specs / endpoints documented |
| 7 | Cloud infrastructure (GCP / AWS / Azure project) | Innodata | Provisioned |
| 8 | Secure data transfer mechanism (SFTP / cloud bucket) | Both | Tested with sample batch |

---

## 3. Team Structure & Roles

### Innodata side

| Role | FTE | Responsibilities |
|---|---:|---|
| **Tech Lead / Architect** | 0.5 | Architecture decisions, prompt engineering, threshold tuning |
| **ML/Pipeline Engineer** | 1.0 | Pipeline configuration, provider integration, scaling |
| **Data Engineer** | 1.0 | Ingestion, storage, orchestration, monitoring |
| **QA / Validation Engineer** | 0.5 | Sample-based audit, Before/After reports, regression checks |
| **Project Manager** | 0.5 | Cadence, SME coordination, client comms, risk tracking |

### Client side

| Role | Effort | Responsibilities |
|---|---|---|
| **Legal/Domain SME (×2)** | ~6 hrs/week each | Review enriched samples, validate taxonomy, sign off on quality |
| **Editorial Lead** | ~4 hrs/week | Seed dictionary curation, taxonomy governance |
| **Engineering Liaison** | ~3 hrs/week | Downstream system integration, schema validation |
| **Sponsor / Decision Maker** | ~1 hr/week | Milestone sign-offs, escalation |

---

## 4. Week-by-Week Plan

### **Week 1 — Discovery & Environment Setup**

**Goal:** Understand the corpus, provision infrastructure, align on success criteria.

#### Engineering activities
- Corpus audit: XML schema variants, document type distribution, size statistics
- Data-quality landmine survey: DOCTYPE entities, comment blocks, processing instructions
- Cloud infrastructure provisioning (compute, storage, vector DB selection)
- LLM provider quota verification and authentication setup
- Code branch from POC baseline; configure for client domain

#### SME activities
- Kickoff workshop: scope, success criteria, taxonomy expectations
- Walk-through of existing editorial taxonomy (if any)
- Identification of "gold standard" reference documents for benchmark

#### Deliverables
- Corpus audit report (volume, doc types, quality issues)
- Infrastructure ready & validated with sample run
- Signed-off success criteria document

#### Exit gate
- ✅ Sample 10-document parse run completes successfully
- ✅ Client + Innodata aligned on success metrics

---

### **Week 2 — Seed Dictionary & Schema Adaptation**

**Goal:** Build the domain-specific seed taxonomy and adapt the pipeline to client XML.

#### Engineering activities
- XML parser adaptation for client schema variants
- Chunking parameter tuning (target word count, lineage breadcrumb format)
- Anchor threshold calibration on sample data
- Embedding model selection (Gemini vs. bge-small) based on cost/latency tests
- Test harness for repeatable runs

#### SME activities
- **Collaborative seed dictionary workshop** (2 sessions, 2 hours each)
  - Curate L1 domain definitions
  - Seed L2 macro-topics (target 50–200 topics across all domains)
  - Seed L4 keyword lists per domain
  - Define organization / case / statute reference lists if available
- Review parser output on 5 representative documents

#### Deliverables
- `master_dictionary.json` (seed taxonomy)
- Adapted XML parser with client-specific normalization
- Calibrated anchor threshold value

#### Exit gate
- ✅ Seed dictionary signed off by SMEs
- ✅ Parser handles 100% of sample documents without errors

---

### **Week 3 — Pilot Run (5,000 Documents)**

**Goal:** Run the full pipeline on a representative 5k-document subset to validate end-to-end behavior at meaningful scale.

#### Engineering activities
- **Phase 1+2 execution** on 5k docs: parse → chunk → dictionary harvest → relationship graph
- **Phase 3 execution**: routing (L1+L2), L4 extraction, L3 clustering
- **Phase 4 execution**: document synthesis, Before/After comparison generation
- Monitor: anchor rate, error rate, token consumption, wall-clock per document
- Generate sample audit packs (50 docs from each major domain)

#### SME activities
- Receive sample audit packs at end of Week 3
- Start review (continues into Week 4)

#### Deliverables
- 5k-document pilot output (chunks + documents + dictionary)
- Pilot metrics dashboard (anchor rate, coverage, cost actuals)
- Sample audit packs ready for SME review

#### Exit gate
- ✅ Pipeline runs end-to-end on 5k docs
- ✅ Anchor rate ≥ 75% (POC achieved 85%)
- ✅ L4 extraction success rate ≥ 95%

---

### **Week 4 — SME Review Cycle 1 + Refinement**

**Goal:** Validate pilot output quality with SMEs; refine prompts, thresholds, dictionary.

#### SME activities — **Review Cycle 1**
- **L2 topic review:** sample 200 chunks; rate L2 assignments (correct / acceptable / wrong)
- **L3 sub-topic review:** review all newly discovered L3 cluster names
- **L4 entity review:** validate cases, statutes, organizations on 100 chunks
- **Coverage gap analysis:** identify domains where discovered taxonomy is thin
- Provide written feedback with examples

#### Engineering activities (responding to SME feedback)
- Prompt refinement based on SME findings
- Threshold tuning if anchor rate too high/low
- Seed dictionary expansion (promote high-confidence discovered topics to seeds)
- Edge-case handling (specific document types that under-performed)
- Re-run pilot on a subset to validate improvements

#### Deliverables
- SME Review Report 1 (with quality scorecard)
- Refined prompts, dictionary, thresholds (versioned)
- Pilot v2 re-run results

#### Exit gate
- ✅ SME quality scorecard ≥ 85% acceptable on L2
- ✅ ≥ 90% acceptable on L4 entities
- ✅ Client sign-off to proceed to full production run

---

### **Week 5 — Production Run Part 1 (75k Documents)**

**Goal:** Execute the first half of the full production enrichment.

#### Engineering activities
- Scale up worker pool (50+ parallel document workers)
- Launch Phase 1+2 on full 150k corpus (~12 hours wall-clock)
- Launch Phase 3.1+3.2 on first 75k documents
- Continuous monitoring: error rate, token spend, throughput
- Daily checkpoint reports
- Spot-check QA on 1% sample as docs complete

#### SME activities — **Rolling Review Cycle 2a**
- Mid-week: review 500-document sample from the first wave
- Flag any quality regressions vs. pilot
- Approve continuation to second wave

#### Deliverables
- 75k documents fully enriched through Phase 3
- Daily progress dashboard
- Mid-run QA report

#### Exit gate
- ✅ 75k docs through Phase 3.1+3.2 without quality regression
- ✅ Cost tracking within ±15% of projection
- ✅ SME approval to launch second wave

---

### **Week 6 — Production Run Part 2 (remaining 75k) + L3 Clustering**

**Goal:** Complete enrichment of the full 150k corpus.

#### Engineering activities
- Phase 3.1+3.2 on remaining 75k documents
- **Phase 3.3 (L3 clustering + naming)** on full 150k corpus once 3.1+3.2 complete
  - Re-embed all chunks (or reuse persisted Phase 3.1 vectors — Lever 2 optimization)
  - Agglomerative clustering per L2 group
  - L3 naming for each cluster
- **Phase 4 (synthesis)** kickoff in parallel with late 3.3
- Generate enriched dictionary
- Generate Before/After comparison reports

#### SME activities — **Rolling Review Cycle 2b**
- Receive sample of completed documents
- Review newly-discovered L3 sub-topics (likely 5,000–10,000 new names)
- Validate top 100 most-frequent L3s
- Flag any naming inconsistencies or near-duplicates

#### Deliverables
- All 150k documents fully enriched
- Final `enriched_dictionary.json`
- Final `final_enriched_documents.json`
- L3 naming review packet

#### Exit gate
- ✅ 100% of 150k documents have L1+L2+L3+L4 populated
- ✅ L4 extraction success ≥ 95% (allowing for genuine no-entity docs)
- ✅ L3 review packet sent to SMEs

---

### **Week 7 — Final QA, Dictionary Refinement, Integration Prep**

**Goal:** Final quality pass, integration with downstream systems, SME sign-off.

#### Engineering activities
- **Statistical QA pass:**
  - Coverage check: 100% of docs have all 4 taxonomy levels
  - Sample audit: 0.5% random sample (750 docs) reviewed against editorial expectations
  - Edge-case audit: very short docs, very long docs, multi-language docs (if applicable)
- **L3 name deduplication** (merge near-duplicate cluster names per SME feedback)
- **Entity canonicalization** (case-fold dedup, title-case normalization)
- **Output transformation** to client's downstream format (vector DB / search index / knowledge graph schema)
- **Integration testing** with target system using sample batch
- **Documentation:** runbooks, API guides, dictionary governance docs

#### SME activities — **Final Review Cycle 3**
- Review final dictionary (promoted L2s, refined L3s, entity indices)
- Sign off on final taxonomy
- Approve representative output samples
- Final acceptance criteria walkthrough

#### Deliverables
- Final enriched corpus (all 5 canonical JSON artifacts)
- Output in client's target format
- QA report (statistical + sample-based)
- Documentation set
- Integration test results

#### Exit gate
- ✅ Final SME sign-off on output quality
- ✅ Sample batch successfully loaded into client target system
- ✅ All documentation reviewed and approved

---

### **Week 8 — Delivery, Handover & Knowledge Transfer**

**Goal:** Hand over the enriched corpus and operational ownership to the client.

#### Engineering activities
- **Final delivery:** transfer full enriched corpus to client environment
- **Operational runbook walkthrough** with client engineering team
- **Incremental enrichment setup:** configure pipeline to process new content going forward
- **Monitoring & alerting** setup for ongoing operation
- **Handover sessions** (2 × 2-hour sessions covering pipeline, dictionary, troubleshooting)
- **Lessons-learned retrospective**

#### SME activities
- Final acceptance test
- Sign-off on production go-live
- Editorial governance training (how to grow seed dictionary over time)

#### Deliverables
- Production-ready enriched corpus, delivered
- Operational documentation set
- Knowledge transfer recordings
- Final project report with metrics, learnings, recommendations
- Signed acceptance certificate

#### Exit gate
- ✅ Client formally accepts delivery
- ✅ Client engineering team can run incremental enrichment independently
- ✅ Final invoice triggered

---

## 5. SME Review Cadence

SMEs are engaged across the project, not just at end-of-phase. The review pattern:

| Week | Review Type | Sample size | SME hours |
|---|---|---:|---:|
| 1 | Kickoff workshop | n/a | 4 |
| 2 | Seed dictionary workshops | n/a | 8 |
| 3 | (engineering only — pilot run) | — | 2 (standup) |
| 4 | **Review Cycle 1** — Pilot output validation | 200 chunks + 100 entities | 16 |
| 5 | Rolling review 2a — first wave check | 500 docs | 6 |
| 6 | Rolling review 2b — L3 names | 100 L3 names | 8 |
| 7 | **Review Cycle 3** — Final acceptance | 750-doc sample | 12 |
| 8 | Final sign-off + governance training | n/a | 6 |

**Total SME effort: ~60 hours per SME** (×2 SMEs = ~120 person-hours across 8 weeks).

### What SMEs look for in each review

| Review type | Checking for |
|---|---|
| **L2 topic review** | Is the macro-topic accurate? Could a different L2 in the dictionary fit better? |
| **L3 sub-topic review** | Is the cluster naming consistent? Are similar clusters merged? Domain-appropriate phrasing? |
| **L4 entity review** | Are case names/statutes correctly extracted and formatted? Any hallucinations? |
| **Keyword review** | Are dictionary-matched keywords genuinely echoed (not paraphrased)? Are new keywords useful additions? |
| **Coverage review** | Are there document types where the pipeline systematically under-performs? |

---

## 6. Milestones & Deliverables

| # | Milestone | Week | Acceptance criteria |
|---|---|---:|---|
| M1 | Discovery complete, environment ready | 1 | Sample run successful |
| M2 | Seed dictionary SME-approved | 2 | Signed off |
| M3 | Pilot run complete (5k docs) | 3 | Anchor rate ≥ 75%, L4 success ≥ 95% |
| M4 | SME Review Cycle 1 passed | 4 | Quality scorecard ≥ 85% |
| M5 | First production wave complete (75k docs) | 5 | No quality regression, cost tracking on plan |
| M6 | Full corpus enriched (150k docs) | 6 | 100% taxonomy coverage |
| M7 | Final QA & integration ready | 7 | SME final sign-off |
| M8 | Delivery & handover complete | 8 | Client acceptance certificate signed |

---

## 7. Risk Register

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | LLM provider rate-limit / quota issue | Medium | High | Pre-approved Vertex quota; multi-region fallback; exponential backoff already built-in |
| R2 | Source XML has schema variants we didn't see in samples | High | Medium | Week-1 corpus audit; defensive parsing; per-document checkpointing limits blast radius |
| R3 | SME availability lower than planned | Medium | High | Async review tooling; clear weekly time commitments upfront; backup reviewer identified |
| R4 | Seed dictionary too small → low anchor rate → high LLM cost | Medium | Medium | Mid-pilot review of anchor rate; promote discovered topics into seed iteratively |
| R5 | L3 clustering produces too many fragmented clusters | Medium | Medium | Cluster threshold tunable; dedup pass in Week 7; SME merge guidance |
| R6 | LLM occasionally hallucinates entities/cases | Low–Medium | Medium | Post-LLM dictionary validation already enforced; SME spot-checks; structured-output schema |
| R7 | Downstream system integration friction | Medium | Medium | Integration testing in Week 7; output schema agreed in Week 1 |
| R8 | Cost overrun (token consumption higher than projected) | Low | Medium | Daily cost tracking from Week 5; budget caps; cost-saving levers (caching, persistence) staged |
| R9 | Editorial scope creep (new doc types added mid-engagement) | Medium | High | Strict change-control process; new doc types deferred to Phase 2 engagement |
| R10 | Client target system not ready for delivery | Low | Medium | Cloud-bucket fallback delivery; format-agnostic JSON artifacts |

---

## 8. Success Metrics

The project will be measured against these metrics at delivery:

### Quantitative

| Metric | Target |
|---|---|
| Documents fully enriched | 150,000 / 150,000 (100%) |
| Documents with L1+L2+L3+L4 populated | ≥ 99% |
| Anchor rate (L2 routing) | ≥ 90% (vs. 84.6% POC) |
| L4 extraction success | ≥ 95% of chunks |
| Discovered L2 topics | ~1,500–3,000 |
| Discovered L3 sub-topics | ~5,000–10,000 |
| Unique case citations extracted | ~50,000–150,000 |
| Unique statute references extracted | ~30,000–80,000 |
| SME quality scorecard (L2 accuracy) | ≥ 90% |
| SME quality scorecard (L4 entities) | ≥ 92% |
| Total LLM spend | Within ±15% of $7,500 budget |
| Wall-clock for full corpus | ≤ 7 days for Phase 3 |

### Qualitative

- SME confidence in output quality (verbal sign-off + written acceptance)
- Successful integration with downstream client system
- Client engineering team able to operate the pipeline independently post-handover
- No critical defects open at delivery

---

## 9. Post-Deployment Handover

After Week 8 delivery, optional follow-on engagement:

### Months 1–3 post-delivery
- **Incremental enrichment** of new content (e.g., monthly batches of 1k–5k new docs)
- **Bug fixes / hot patches** under SLA
- **Dictionary refresh** quarterly (promote high-frequency discovered topics into seed)

### Optional managed service
- Innodata operates the pipeline on an ongoing basis
- Monthly QA reports
- Quarterly taxonomy governance review
- Annual prompt / model refresh as LLM ecosystem evolves

---

## Appendix A — Detailed Week-by-Week Effort Allocation

| Week | Tech Lead | ML Eng | Data Eng | QA Eng | PM | SME (×2) |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 30h | 40h | 40h | 10h | 20h | 8h |
| 2 | 30h | 40h | 30h | 10h | 20h | 16h |
| 3 | 20h | 40h | 40h | 20h | 20h | 4h |
| 4 | 20h | 30h | 20h | 30h | 20h | 32h |
| 5 | 20h | 40h | 40h | 30h | 20h | 12h |
| 6 | 20h | 40h | 40h | 30h | 20h | 16h |
| 7 | 30h | 30h | 30h | 40h | 20h | 24h |
| 8 | 20h | 20h | 20h | 20h | 20h | 12h |
| **Total** | **190h** | **280h** | **260h** | **190h** | **160h** | **124h** |

≈ 1,080 Innodata person-hours + 124 SME person-hours.

---

## Appendix B — Communication Cadence

| Frequency | Forum | Participants | Duration |
|---|---|---|---|
| Daily (Week 5–6) | Engineering standup | Innodata team | 15 min |
| Weekly | Status review | Innodata + Client PM + Sponsor | 45 min |
| Weekly | SME review session | SMEs + Tech Lead + QA | 60 min |
| Bi-weekly | Steering committee | Sponsors + PM | 30 min |
| Ad-hoc | Slack/Teams channel | All hands | continuous |

---

## Appendix C — What Happens If We Slip

Pre-defined response plans for common slip scenarios:

| Slip scenario | Response |
|---|---|
| Week-2 dictionary not signed off | Run pilot anyway on best-effort seed; iterate dictionary in parallel |
| Week-3 pilot anchor rate < 70% | Pause; expand seed dictionary; re-run pilot before proceeding |
| Week-4 SME quality scorecard < 80% | Hold production launch; prompt iteration sprint; re-pilot subset |
| Week-5 cost overrun > 25% | Switch to Flash-Lite for L4 extraction; enable prompt caching ahead of schedule |
| Week-6 L3 clustering produces > 15k clusters | Increase agglomerative threshold; re-cluster; trade granularity for coherence |
| Week-7 integration blocker | Deliver canonical JSON output; integration deferred to follow-on |

---

**Document version:** 1.0
**Owner:** Innodata Project Manager
**Stakeholders:** Client Sponsor, Client Editorial Lead, Innodata Tech Lead
