# Insight Engine — API Requirements (for the React UI)

Analysis of the backend API needed to power the 6-screen multi-file React UI
(Upload → Confirm → Processing → Batch Results → Result Explorer → History).

---

## 1. The core gap

The pipeline today is a **synchronous, file-based CLI**. Each phase is a
`python -m …` command that reads a JSON artifact and writes the next one.
A React app cannot consume that directly. Three gaps must be closed:

| Gap | Today | Needed for the UI |
|---|---|---|
| **Interface** | CLI commands, JSON files on disk | HTTP/JSON API (recommend **FastAPI** — same Python, async, OpenAPI built-in) |
| **Execution** | Runs to completion in the foreground (~minutes/doc) | **Async jobs** + status tracking so Upload returns instantly and Processing streams progress |
| **Persistence** | Loose JSON files per run | A **datastore** (batches, files, documents, taxonomy) so History/Results are queryable |
| **PDF/DOC ingestion** | XML only (`rag_parser` needs KEA-BASIC structure) | A **text-extraction + structure-synthesis** path; domain supplied by the user (no `cust-group`) |

These are backend build items — they block the UI regardless of how the React
side is written.

---

## 2. Recommended stack

- **API**: FastAPI + Pydantic (typed request/response, auto OpenAPI → free TS client)
- **Async jobs**: start with FastAPI `BackgroundTasks` (MVP); move to **Celery/RQ/arq + Redis** for the 150k-scale worker pool the proposal describes
- **Persistence (MVP)**: SQLite + JSON blobs on disk, keyed by id. **(Prod)**: Postgres + object store (S3/GCS) + vector store — matches the proposal's scaling plan
- **Real-time progress**: **Server-Sent Events (SSE)** — one-way server→client, perfect for progress, simpler than WebSockets

---

## 3. Data model

```
Batch
  id, created_at, status (draft|processing|complete|partial_failure),
  file_count, summary { enriched, chunks, coverage_pct, failed }
  └── Files[]
        id, batch_id, filename, size, format (xml|pdf|docx),
        domain (KA|KCL|null), needs_domain (bool),
        status (pending|queued|extracting|parsing|chunking|enriching|synthesizing|done|failed),
        phase_progress (0..1), error?
        └── Document  (1:1, created when enrichment completes)
              doc_id, doc_type, container_title, publ_year, domain,
              case_metadata?,  taxonomy {…},  chunk_count,
              before { editorial_topics[], editorial_keywords[] }
```

`Document.taxonomy` is the Phase 4 rollup, **plus** a tree composition for the
Explorer (see §5, note on the tree).

---

## 4. Screen → data needs → endpoints

| Screen | Needs | Endpoint(s) |
|---|---|---|
| **1 Upload** | Upload N files; auto-detect domain for XML; flag PDF/DOC as "needs domain"; validate type/size | `POST /api/files` (multipart) ; `DELETE /api/files/{id}` |
| **2 Confirm** | Assign KA/KCL to each PDF/DOC; XML locked | `PATCH /api/files/{id}` `{domain}` |
| **3 Processing** | Start batch; live per-file + per-phase progress; overall %, ETA | `POST /api/batches` ; `GET /api/batches/{id}/events` (SSE) ; `GET /api/batches/{id}` (poll fallback) |
| **4 Batch Results** | Summary stats + per-file row (domain, top topic, level coverage, status) | `GET /api/batches/{id}/results` |
| **5 Result Explorer** | Full L1–L4 tree w/ provenance; Entities tab; Before/After; file pager across batch; export | `GET /api/documents/{id}` ; `GET /api/documents/{id}/before-after` ; `GET /api/documents/{id}/export` |
| **6 History** | Batches grouped by date; searchable/filterable/sortable document list | `GET /api/batches` ; `GET /api/documents?search=&domain=&type=&sort=&page=` |

---

## 5. Endpoint reference (MVP)

### Upload & confirm

```
POST /api/files                        # multipart, 1..N files
→ 201 [
   { id, filename, size, format:"xml",  domain:"KA", needs_domain:false, status:"pending" },
   { id, filename, size, format:"pdf",  domain:null,  needs_domain:true,  status:"pending",
     text_preview:"…the arbitral tribunal held…" }
  ]
# XML: server strips landmines, parses cust-group → auto domain.
# PDF/DOC: server extracts text, returns preview, marks needs_domain.

PATCH /api/files/{id}   { "domain": "KA" }     → 200 updated file
DELETE /api/files/{id}                          → 204
```

### Batch lifecycle

```
POST /api/batches   { "file_ids": ["…","…"] }
→ 202 { batch_id, status:"processing" }         # validates every PDF/DOC has a domain, then starts the job

GET /api/batches/{id}
→ 200 {
    id, status, overall_progress: 0.5, eta_seconds: 60,
    files: [
      { id, filename, domain, status:"done",       phase:"synthesize", progress:1,
        document_id, top_topic:"Arbitrator Independence" },
      { id, filename, domain, status:"enriching",  phase:"enrich",     progress:0.4 },
      { id, filename, domain, status:"queued",     phase:null,         progress:0 },
      { id, filename, domain, status:"failed",     error:"…" }
    ]
  }

GET /api/batches/{id}/events            # SSE stream of the object above as phases advance
  event: progress  data: { file_id, status, phase, progress, overall_progress }
  event: done       data: { batch_id }

GET /api/batches/{id}/results
→ 200 {
    summary: { enriched:4, chunks:18, coverage_pct:100, failed:0 },
    documents: [
      { document_id, filename, domain:"KA", top_topic:"Arbitrator Independence",
        levels:"L1-L4", status:"done" }, …
    ]
  }
```

### Document (taxonomy)

```
GET /api/documents/{id}
→ 200 {
    doc_id, filename, doc_type, domain, container_title, publ_year, chunk_count,
    case_metadata: { court, case_name, case_number, decision_date, parties:[…] } | null,
    provenance: { summary:"50% Anchored, 50% Expanded", anchored_pct, expanded_pct },
    taxonomy_tree: [                                  # composed for the Explorer (see note)
      { level:"L1", label:"International Arbitration", children:[
        { level:"L2", label:"Arbitrator Independence", source:"anchor", similarity:0.81,
          children:[
            { level:"L3", label:"Arbitrator Issue Conflict", children:[
              { level:"L4", kind:"cases",    values:["DJP v. DJO","Halliburton v. Chubb"] },
              { level:"L4", kind:"statutes", values:["International Arbitration Act s.16"] },
              { level:"L4", kind:"keywords", values:["Arbitrator Bias","Prejudgment"] }
            ]}
          ]},
        { level:"L2", label:"Arbitrator Bias Standards", source:"generator", similarity:0.70, children:[…] }
      ]}
    ],
    entities: {                                       # flat, for the Entities tab
      case_names:[…], statutes_and_regulations:[…], organizations:[…]
    },
    keywords: { all:[…], matched_from_dictionary:[…], newly_extracted:[…] }
  }

GET /api/documents/{id}/before-after
→ 200 {
    before: { topics:["…"], keywords:["…"], cases:[], statutes:[], organizations:[] },
    after:  { /* taxonomy summary as above */ },
    uplift: { levels_before:2, levels_after:6 }
  }

GET /api/documents/{id}/export?format=json|csv      → file download
GET /api/documents/{id}/chunks                       # optional drill-down (chunk-level L1–L4 + audit fields)
```

> **Note — the Explorer tree needs chunk-level data.** `synthesize.py` produces a
> *flat* doc rollup (L2_All_Topics, a flat L3 list, flat L4 sets). The Explorer's
> nested **L2 → L3 → L4** tree only exists at the chunk level (each chunk carries
> its own L2/L3/L4 + `L2_Source`/`L2_Similarity`). So `GET /api/documents/{id}`
> must **compose the tree by grouping the document's chunks by L2→L3 and
> aggregating L4** — this is new logic on top of the current Phase 4 output.

### History list

```
GET /api/batches?page=&page_size=                   # grouped-by-date history
GET /api/documents?search=&domain=KA&type=commentary&sort=newest&page=
→ 200 { total, page, items:[ { document_id, filename, domain, top_topic, levels, processed_at } ] }
```

### Later phases (not MVP)

```
GET /api/dictionary?domain=KA        # seed vs discovered topics (expand_dictionary.py) — editorial governance
GET /api/documents/{id}/relationships # xref graph edges (relationship_extractor.py) — knowledge-graph view
POST /api/auth/login                  # per-user History/scoping
```

---

## 6. Three backend items that block the UI

1. **PDF/DOC ingestion path** (new). `rag_parser` is XML-only. Need: text
   extraction (e.g. `pdfplumber`/`python-docx`) → synthesize a minimal parsed-doc
   shape (sections from text, `cust_groups=[user_domain]`, `doc_type` essay-like)
   → feed Phase 2 onward. Without this, "multi-format upload" is XML-only.

2. **Async job runner + status model** (new). Wrap the 4 phases as a per-file job
   that writes `status`/`phase`/`progress` to the datastore and emits SSE events.
   The proposal's checkpointing maps cleanly to per-phase status rows.

3. **Taxonomy-tree composition** (new). Group chunks by L2→L3, aggregate L4, carry
   `L2_Source`/`L2_Similarity` provenance — to feed the Explorer tree and the
   anchored/expanded badges.

Everything else (parse, chunk, route, L3/L4, synthesize) already exists and is
reused as-is behind the job runner.

---

## 7. Cross-cutting

- **Validation**: accepted formats (`xml`,`pdf`,`docx`), max size, reject empties; per-file errors must not fail the whole batch (`status:"partial_failure"`).
- **Errors**: consistent `{ error: { code, message, detail? } }`; surface per-file failures in Processing/Results.
- **Pagination**: `page`/`page_size` on all list endpoints (History scales to 150k docs).
- **Idempotency / resume**: a failed batch can be re-run per-file (the pipeline is already resumable by design).
- **Auth**: MVP can defer; History implies per-user scoping eventually.
- **CORS**: enable for the React dev origin.

---

## 8. Suggested build order

1. **FastAPI skeleton** + datastore + file upload/validation (`POST /api/files`, XML auto-domain, PDF/DOC preview)
2. **Job runner** wrapping the existing pipeline + per-file status + **SSE** (`POST /api/batches`, `/events`)
3. **Document read APIs** + **tree composition** + before/after (`GET /api/documents/{id}`, `/before-after`)
4. **History/list** + search/filter/pagination
5. **PDF/DOC extraction** path (can ship XML-only first, add this next)
6. Later: dictionary, relationships, auth, export-CSV

Then the React app is a straightforward consumer: upload form → SSE progress →
results table → taxonomy tree/entities → history list.
```
