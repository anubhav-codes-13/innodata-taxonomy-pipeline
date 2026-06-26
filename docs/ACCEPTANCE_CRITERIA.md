# Acceptance Criteria — Taxonomy Process

## A. Taxonomy Design & Structure

| Criterion | Target | How measured |
|-----------|--------|--------------|
| **Mutually Exclusive (per facet)** — within one axis, a term belongs to one clear place | No ambiguous overlaps within a facet | Structural audit; MECE check |
| **Collectively Exhaustive (coverage)** — the vocabulary covers the corpus's subject matter | ≥ 95% of documents map to a non-"miscellaneous" term | % of docs landing in a valid category vs. "uncategorised" |
| **Consistent granularity** — sibling terms sit at comparable levels of specificity | Level homogeneity verified per branch | Reviewer audit against design rules |
| **Standards alignment** — facets map to a recognised legal standard | 100% of top-level Areas of Law mapped to SALI/Seed URIs | Mapping coverage report |
| **No orphans / no near-duplicates** | 0 unmapped or synonymous-duplicate terms | Automated dup/orphan scan |
| **Multi-axis (faceted)** — jurisdiction, doc type, process, practice area are independent | All four facets present and independently assignable | Schema review |
| **Versioned & documented** | Every release version-stamped with definitions | Governance record |

## B. Classification / Auto-Tagging Accuracy

| Criterion | Recommended target | Notes |
|-----------|-------------------|-------|
| **Precision** (tags assigned that are correct) | ≥ 0.90 for primary facets | High precision matters most in legal — a wrong tag misleads |
| **Recall** (correct tags that were found) | ≥ 0.80 | Trade-off with precision; tune per facet |
| **F1 score** (harmonic mean) | ≥ 0.85 per facet | The standard single acceptance number |
| **Confidence-thresholded auto-accept** | Auto-accept above a calibrated confidence; below → human review | Where estimated F1 ≥ agreed minimum, no human review required |
| **Citation/entity normalization accuracy** | ≥ 0.95 exact-match to canonical form | Legal-specific; "Article 54" variants → one reference |
| **No critical misclassification** | 0 high-risk errors (e.g., wrong jurisdiction) in the gold set | Legal risk gate |

## C. Label Reliability (Gold Standard)

| Criterion | Target | Notes |
|-----------|--------|-------|
| **Inter-annotator agreement** (Cohen's κ for 2 raters, Fleiss' κ for 3+) | κ ≥ 0.70 minimum; ≥ 0.80 preferred | 0.70 is the common production-ML floor; 0.81–1.00 = "almost perfect" (Landis & Koch) |
| **Adjudication of disagreements** | 100% of κ-flagged conflicts resolved before gold set is frozen | Reviewer reconciliation log |

## D. Self-Healing / Evaluation Process

| Criterion | Target | How measured |
|-----------|--------|--------------|
| **Keep precision** (terms kept that are genuinely useful) | ≥ 0.95 | Sample audit of auto-kept terms |
| **False-discard rate** (useful terms wrongly discarded) | ≤ 2% | Sample audit of auto-discarded terms |
| **Auto-resolution rate** (share resolved without a human) | ≥ 85% (rising over time) | Pipeline telemetry |
| **Sampling-QA error tolerance** | Audited error on auto-decisions < 2%; if exceeded → tighten thresholds | Random-sample QA, each cycle |
| **Human-queue containment** | Expert-review volume within agreed staffing capacity | Queue depth monitoring |
| **Decision permanence** | 100% of expert decisions persisted to Memory (never re-asked) | Memory audit |

## E. Findability & User Validation

| Criterion | Target | How measured |
|-----------|--------|--------------|
| **Tree-test task success** | ≥ 80% of users find the right term/document | Tree testing (reverse card sort) |
| **Closed card-sort agreement** | Users sort terms into intended categories at high agreement | Closed card sort |
| **Label intuitiveness** | Names match users' mental models (no jargon mismatches) | User testing feedback |
