# Insight Engine — Startup Instructions

## Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| Python | 3.10+ | |
| Node.js | 18+ | |
| npm | 9+ | bundled with Node |
| MySQL | 8.0 | must be running as service `MySQL80` |

---

## 1 — Backend setup

```bash
# From the repo root
cd api

# Create a virtual environment (first time only)
python -m venv .venv

# Activate it
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# Windows CMD:
.venv\Scripts\activate.bat
# macOS / Linux:
source .venv/bin/activate

# Install dependencies (first time only)
pip install -r ../requirements-api.txt
```

### Environment variables (optional)

Create a `.env` file in the repo root or set these in your shell before starting:

```
# Google Gemini API key (leave unset to use the offline dummy provider)
GOOGLE_API_KEY=your_key_here

# Storage directory (defaults to <repo>/storage/)
IE_STORAGE_DIR=storage

# CORS origins for the dev frontend
IE_CORS_ORIGINS=http://localhost:5173
```

### Start the backend

```bash
# From the repo root (with .venv activated)
python run_api.py
```

The API server starts at **http://localhost:8000**.  
Swagger docs: http://localhost:8000/docs

---

## 2 — Frontend setup

```bash
# From the repo root
cd frontend

# Install dependencies (first time only)
npm install

# Start the dev server
npm run dev
```

The app opens at **http://localhost:5173**.

---

## 3 — Running both together

Open **two terminals** from the repo root:

**Terminal 1 — Backend**
```powershell
api\.venv\Scripts\python.exe run_api.py
```

**Terminal 2 — Frontend**
```powershell
cd frontend
npm run dev
```

Then open **http://localhost:5173** in your browser.

---

## Project structure (key folders)

```
Insight_engine_backend-wolters_kulwer_demo/
├── api/                  FastAPI backend
│   ├── routers/          API route handlers
│   ├── documents.py      Taxonomy composition
│   ├── store.py          SQLite helpers
│   └── schemas.py        Pydantic models
├── src/                  Enrichment pipeline (Phase 3 / 4)
│   ├── phase3/           L2/L3/L4 enrichment
│   └── phase4/           Synthesis / taxonomy rollup
├── frontend/             React + Vite UI
│   └── src/
│       ├── screens/      Page components
│       ├── lib/          API client, hooks, types
│       └── mocks/        In-memory mock for dev/demo
├── storage/              Runtime data (auto-created)
│   ├── uploads/          Uploaded files
│   ├── enriched/         Phase-4 taxonomy JSON per file
│   └── enriched_chunks/  Per-chunk L1–L4 JSON per file
├── data/                 Master dictionary & seed data
├── KA-xml-samples/       Sample KA (Arbitration) XML files
├── KCL-xml-samples/      Sample KCL (Competition Law) XML files
├── run_api.py            Backend entry point
└── requirements-api.txt  Python dependencies
```
