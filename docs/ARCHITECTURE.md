# TraceAI — Codebase Walkthrough

A file-by-file explanation of what each source file does and why it exists.

---

## Architecture Overview

```
User (Browser)
    │
    ▼
┌─────────────────────┐
│  Frontend (Next.js)  │  page.tsx → UI, files, matrix, evaluations, impact
│  localhost:3000      │  lib/tracing.ts → scoring constants & calculations
└────────┬────────────┘
         │ HTTP
         ▼
┌─────────────────────────────────────────────────────────┐
│  Backend (FastAPI)   api.py → REST endpoints            │
│  localhost:8100                                         │
│                                                         │
│  ┌─────────────────┐  github_integration.py ◄─── Git    │
│  │ persistence.py  │◄─ Sync pipeline                    │
│  │ reranker.py     │                                    │
│  │ bm25_index.py   │                                    │
│  │ explainer.py    │◄─ RAG explainer using Gemini LLM   │
│  │ report_export.py│── PDF / CSV generator              │
│  └───────┬─────────┘                                    │
│          │                                              │
│    ┌─────┴─────┐                                        │
│    ▼           ▼                                        │
│  Qdrant    Postgres                                     │
│ (vectors)  (records)                                    │
└─────────────────────────────────────────────────────────┘
```

---

## Core Backend — `src/traceai_v2/`

### `api.py`

**What:** FastAPI REST endpoints. The HTTP interface for the application.

**Key endpoints:**
- `POST /api/projects` — Creates projects
- `POST /api/projects/{id}/requirements/upload` — Accepts PDF/DOCX/TXT requirements files and triggers parsing & embedding
- `POST /api/projects/{id}/repo/ingest` — Ingests a local repository path
- `POST /api/projects/{id}/trace-links/generate` — Runs the hybrid retrieval & rerank pipeline
- `GET /api/projects/{id}/trace-matrix` — Assembles the trace link matrix with gold standard evaluations
- `POST /api/projects/{id}/sync` — Syncs a GitHub project incrementally
- `GET /api/projects/{id}/runs/{run_id}/requirements/{req_id}/explanation` — Computes/retrieves RAG-based natural language trace explanations
- `GET /api/projects/{id}/runs/{run_id}/export/pdf` / `/export/csv` — Streams report documents
- `GET /api/projects/{id}/impact` — Generates impact analysis risks and blast radius metrics

**Why it exists:** Decouples the UI and consumer applications from the core business logic.

---

### `persistence.py` ⭐ THE CORE PIPELINE

**What:** Contains the core trace link generation, trace matrix construction, and impact analysis pipelines.

**Key features:**
1. **`generate_trace_links()`**:
   - Performs **Query Expansion** for Exception (`E-type`) flows by prepending parent Use Case S-flow text context.
   - Runs **semantic search** against Qdrant to retrieve vector candidates.
   - Runs **BM25 keyword search** over code paths and chunks.
   - Merges candidate lists using **Reciprocal Rank Fusion (RRF)**.
   - Passes candidates to `reranker.py` for **Cross-Encoder reranking**.
   - Performs **File-Level Aggregation** by selecting the maximum chunk score for each file.
   - Saves trace links with calibrated similarity scores.
2. **`build_trace_matrix()`**:
   - Collects database records.
   - Matches generated links against the gold standard CSV (`gold_links_itrust.csv`) using a path lookup helper `_find_gold_csv`.
   - Runs evaluation metrics calculations (Hit@k, MRR, NDCG@k, MAP, Precision, Recall, F1).
3. **`build_impact_analysis()`**:
   - Retrieves all code units and trace links associated with a file path.
   - Details affected requirements and calculates risk score assessments (Low, Medium, High).

---

### `explainer.py` (RAG Generator)

**What:** RAG (Retrieval-Augmented Generation) pipeline for generating natural language descriptions of trace links.

**How it works:**
1. Takes matching requirement texts and source code snippets.
2. Formulates a prompt instructing Gemini to explain why the requirement and code snippet match in 1 or 2 professional sentences.
3. Queries `gemini-2.5-flash` via the Google GenAI SDK.
4. Caches the resulting explanation string in the PostgreSQL database (`trace_links_v2`) to eliminate redundant LLM calls.

---

### `github_integration.py`

**What:** Git workspace manager for cloning, pulling, and diffing remote code repositories.

**Key functions:**
- `clone_or_pull()` — Clones a remote repository or pulls modifications to keep local folders updated.
- `get_commit_diff()` — Runs `git diff` to extract files changed between two commit SHAs, enabling incremental syncs.

---

### `report_export.py`

**What:** Streams styled documents for CSV and PDF reports.

**How it works:**
- Creates standard CSV grids using `csv.DictWriter`.
- Compiles PDF report files using **ReportLab**, applying custom typography, metadata blocks, tables, and color styling.

---

### `reranker.py`

**What:** Cross-encoder reranking using `ms-marco-MiniLM-L-6-v2`.

**How it works:**
- Takes query-document pairs, tokenizes them, and feeds them into a BERT-based relevance model.
- Calibrates embedding similarities with deep cross-attention scores.

---

### `bm25_index.py`

**What:** Tokenizes code chunks (splitting camelCase/PascalCase structures) and builds a local BM25 inverse document frequency index to capture exact keyword matches.

---

### `embeddings.py`

**What:** Pluggable wrapper for embedding providers. Supports:
- `local` (SentenceTransformers BAAI/bge-base-en-v1.5)
- `gemini` (Google Cloud `gemini-embedding-001`)
- `huggingface` (Inference API)
- `hash` (Deterministic fake embeddings for quick tests)

---

### `repo_ingestion.py`

**What:** Walks folders, skips ignores, and utilizes **Tree-sitter AST** to parse classes, functions, and methods into structured code units of ~1200 characters.

---

### `requirements_ingestion.py`

**What:** Parses and extracts textual requirements from PDF, DOCX, TXT, MD, and CSV files, normalizing requirement keys.

---

### `vector_store.py`

**What:** Interface wrapper for Qdrant collection creation, payload querying, and deletion operations.

---

### `storage.py`

**What:** SQLAlchemy schemas and database configuration models:
- `ProjectRecord` — Project metadata, commit SHA, counts, and run dates.
- `RequirementRecord` — Requirement texts and source document paths.
- `CodeUnitRecord` — Tree-sitter code snippet content, line positions, and symbols.
- `TraceLinkRecord` — Trace links mapping requirement to code units, scores, ranks, and cached explanation summaries.
- `AnalysisRunRecord` — Analysis execution histories, timings, and diff lists.

---

## Frontend — `frontend/src/`

### `src/app/page.tsx`

**What:** TraceAI Single-Page Dashboard. Handles:
- UI forms for uploading requirements, registering directories, and triggering runs.
- Rendering summary cards (Completion %, Coverage %, MRR, Hit@k).
- Displaying interactive trace link rows, color-coded by confidence.
- Displaying trace details modals showing code snippets and loading lazy RAG explanations on click.
- Impact analysis tab displaying risk levels of modified files.

### `src/lib/tracing.ts`

**What:** Core client utility and mathematical clamping calculations.
- Clamps BM25/RRF scores into the `[0.0, 1.0]` cosine similarity bounds.
- Synchronizes status thresholds (`IMPLEMENTED = 0.50`, `PARTIAL = 0.38`).
- Computes confidence buckets (`STRONG = 0.65`, `MODERATE = 0.50`, `WEAK = 0.30`).
- Computes mean score values and aggregates coverage counts for charts.

---

## Data Flow Summary

```
Code Ingest (Tree-sitter) ──► Qdrant Vectors + Postgres Records
Requirements Ingest       ──► Qdrant Vectors + Postgres Records
                                     │
                                     ▼
                            persistence.py (RRF Hybrid Search)
                                     │
                                     ▼
                            Rerank (ms-marco) & Aggregation
                                     │
                                     ▼
                           Trace Links Generated
                                     │
                 ┌───────────────────┴───────────────────┐
                 ▼                                       ▼
    Impact Analysis (Risk evaluation)       RAG explanations (Gemini)
                 │                                       │
                 ▼                                       ▼
          Frontend Dashboard ◄───────────────────────────┘
```
