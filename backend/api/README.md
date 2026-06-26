# Insight Engine API

FastAPI service that the React front-end calls. This first slice implements the
**Upload** API — files are stored on the **local device** (disk) with a SQLite
metadata index.

## Layout

```
api/
├── main.py            FastAPI app, CORS, error envelope, startup
├── config.py          storage paths, size limit, allowed types, CORS origins
├── schemas.py         Pydantic models (the React/OpenAPI contract)
├── store.py           SQLite metadata index (stdlib sqlite3, no ORM)
├── ingest.py          XML domain auto-detect + PDF/DOC text preview
└── routers/
    └── files.py       /api/files endpoints
```

Local storage is created on first run:

```
storage/
├── uploads/            raw files, named <file_id><ext>
└── insight_engine.db   metadata
```

## Run

```bash
pip install -r requirements.txt        # pipeline deps (reused for XML domain detect)
pip install -r requirements-api.txt    # API deps
python run_api.py                       # dev server with a source-scoped reloader
```

Interactive docs: <http://localhost:8000/docs>

> **Use `python run_api.py`, not `uvicorn api.main:app --reload`.** The bare
> `--reload` watches the whole tree including `api/.venv`; under OneDrive, sync
> touches site-packages files and triggers an endless reload loop. `run_api.py`
> scopes the watcher to `api/` and `src/` only.

Override storage location / limits via env vars:

```bash
IE_STORAGE_DIR=/data/insight   IE_MAX_FILE_SIZE_MB=50   uvicorn api.main:app
```

## Upload API

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/files` | Upload 1..N files (multipart). Streams to disk with a size cap. XML → domain auto-detected; PDF/DOC → text preview + `needs_domain`. |
| `GET` | `/api/files` | List uploaded files (newest first). |
| `GET` | `/api/files/{id}` | Fetch one. |
| `PATCH` | `/api/files/{id}` | Assign/correct domain — body `{ "domain": "KA" \| "KCL" }`. |
| `DELETE` | `/api/files/{id}` | Remove metadata + on-disk binary. |

### Example

```bash
# upload an XML (domain auto-detected) and a PDF (needs a domain)
curl -F "files=@KA-xml-samples/KA-xml-samples/KLI-JOIA-420502.xml" \
     -F "files=@contract_draft.pdf" \
     http://localhost:8000/api/files
```

Response `201`:

```json
[
  { "id": "9f3c…", "filename": "KLI-JOIA-420502.xml", "size": 84213,
    "format": "xml", "domain": "KA", "needs_domain": false,
    "domain_source": "auto", "status": "pending", "text_preview": null,
    "created_at": "2026-06-19T10:12:00Z" },
  { "id": "1a77…", "filename": "contract_draft.pdf", "size": 1283910,
    "format": "pdf", "domain": null, "needs_domain": true,
    "domain_source": null, "status": "pending",
    "text_preview": "…the arbitral tribunal held that an issue conflict…",
    "created_at": "2026-06-19T10:12:00Z" }
]
```

```bash
# set the PDF's domain (Confirm screen)
curl -X PATCH http://localhost:8000/api/files/1a77… \
     -H "Content-Type: application/json" -d '{"domain":"KA"}'
```

Errors use a consistent envelope: `{ "error": { "code": 415, "message": "…" } }`.

## How this slots into the pipeline

Upload **lands and classifies** files; `POST /api/process` then runs the full
pipeline per file as a background job, streaming progress on `GET /api/events`:

```
queued → parsing → chunking → routing → enriching → synthesizing → done
```

Per file the pipeline writes three artifacts under `storage/`:

| Stage | Output |
|---|---|
| chunk | `chunks/<file_id>.json` — retrieval chunks |
| route + L3 + L4 | `enriched_chunks/<file_id>.json` — chunks with L1–L4 fields |
| synthesize | `enriched/<file_id>.json` — the document's L1–L4 taxonomy |

**Enrichment providers** (`config.ENRICH_PROVIDER`, env `IE_ENRICH_PROVIDER`):

- `auto` (default) — real Gemini when `GOOGLE_API_KEY`/`GEMINI_API_KEY` is set,
  otherwise offline deterministic dummies so the pipeline runs with no key.
- `gemini` — force Gemini (requires a key).  `dummy` — force offline.

Other knobs: `IE_MASTER_DICT` (taxonomy dictionary path), `IE_ENABLE_L3=0`
(skip the L3 clustering stage). See [`../API_REQUIREMENTS.md`](../API_REQUIREMENTS.md).

> **Still open:** a `GET /api/documents/{id}` endpoint to serve the synthesized
> taxonomy to the Result screen, and PDF/DOC text extraction (upload extracts a
> *preview* only today — XML runs end-to-end).
