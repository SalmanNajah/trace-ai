# TraceAI — Codebase Walkthrough

A file-by-file explanation of what each source file does and why it exists.

---

## Architecture Overview

```
User (Browser)
    │
    ▼
┌─────────────────────┐
│  Frontend (Next.js)  │  page.tsx → UI, file upload, trace matrix
│  localhost:3000      │
└────────┬────────────┘
         │ HTTP
         ▼
┌─────────────────────┐
│  Backend (FastAPI)   │  api.py → REST endpoints
│  localhost:8100      │
│                      │
│  ┌────────────────┐  │
│  │ persistence.py │◄─│── Core pipeline: retrieval + reranking
│  │ reranker.py    │  │
│  │ bm25_index.py  │  │
│  └───────┬────────┘  │
│          │           │
│    ┌─────┴─────┐     │
│    ▼           ▼     │
│  Qdrant    Postgres  │
│ (vectors)  (records) │
└─────────────────────┘
```

---

## Core Backend — `src/traceai_v2/`

### `api.py` (269 lines)

**What:** FastAPI REST endpoints. The HTTP interface for everything.

**Key endpoints:**
- `POST /requirements/upload` — accepts PDF/DOCX/TXT, triggers parsing + embedding
- `POST /repo/ingest` — accepts a local path, triggers code parsing + embedding
- `POST /trace-links/generate` — runs the retrieval pipeline
- `GET /trace-matrix` — returns the full matrix for the UI

**Why it exists:** Decouples the UI from the business logic. The frontend only talks HTTP.

---

### `persistence.py` (482 lines) ⭐ THE CORE

**What:** The brain of the system. Contains the full trace link generation pipeline.

**Key function — `search_and_trace()`:**
1. For each requirement, embeds the query text
2. Runs **semantic search** (Qdrant) → gets top-k vector matches
3. Runs **BM25 keyword search** → gets top-k keyword matches
4. Merges results using **Reciprocal Rank Fusion (RRF)**
5. Sends top 80 chunks to the **cross-encoder reranker**
6. **Aggregates per file** (takes max score across chunks from same file)
7. Stores trace links in Postgres

**Also contains:**
- `build_trace_matrix()` — assembles the UI response from DB records
- `_score_to_label()` — maps scores to Implemented/Partial/Missing
- Project reset/clear functions

**Why it exists:** Separates the retrieval pipeline from the API layer. All the research-critical logic lives here.

---

### `reranker.py` (164 lines)

**What:** Cross-encoder reranking using `ms-marco-MiniLM-L-6-v2`.

**How it works:**
1. Takes requirement text + code chunk pairs
2. Feeds each pair to the cross-encoder (a BERT model trained for relevance scoring)
3. Outputs a relevance score per pair
4. Combines with the original RRF score: `0.4 × CE + 0.6 × RRF`

**Why it exists:** Embedding models rank candidates by general similarity. The cross-encoder does pairwise comparison — it can catch matches that embeddings miss (e.g., "error handling" → `AuthDAO.java`). It's slower but more accurate.

---

### `bm25_index.py` (85 lines)

**What:** Custom BM25 (Best Matching 25) keyword search implementation.

**How it works:**
1. Tokenizes code content with camelCase/PascalCase splitting (`AuthDAO` → `auth`, `dao`)
2. Builds inverse document frequency (IDF) for each token
3. At search time, scores documents by keyword overlap with the query

**Why it exists:** Semantic embeddings miss exact keyword matches. If a requirement says "AuthDAO", BM25 will find `AuthDAO.java` directly — embeddings might not because they encode meaning, not words.

---

### `embeddings.py` (309 lines)

**What:** Text-to-vector embedding with multiple provider support.

**Providers:**
- `local` (default) — runs `BAAI/bge-base-en-v1.5` locally via sentence-transformers
- `huggingface` — calls HF Inference API
- `gemini` — calls Google's embedding API
- `hash` — deterministic hash-based vectors (for testing, zero quality)

**Why it exists:** Abstracts away the embedding provider. You can switch between local/API/test modes by changing one env var without touching any pipeline code.

---

### `repo_ingestion.py` (543 lines)

**What:** Parses source code repositories into indexable chunks.

**How it works:**
1. Walks the directory tree, skipping `node_modules`, `.git`, config files, etc.
2. Uses **Tree-sitter** AST parser to extract functions, classes, and methods
3. Falls back to regex-based chunking for unsupported languages
4. Splits large code units into ~1200 char chunks
5. Embeds each chunk and stores in both Postgres and Qdrant

**Supported languages:** Python, JavaScript, TypeScript, TSX, Java, C, C++, Go, Rust, Ruby, C#

**Why it exists:** Raw source files are too large for embedding models. AST parsing produces meaningful, function-level chunks that embed well.

---

### `requirements_ingestion.py` (402 lines)

**What:** Parses requirements documents into individual requirement records.

**Supported formats:** PDF, DOCX, TXT, Markdown, CSV

**How it works:**
1. Extracts raw text from the uploaded file
2. Splits into individual requirements (by numbered patterns, blank lines, or rows)
3. Detects embedded keys (e.g., `REQ-001:`) and uses them as IDs
4. Assigns auto-generated keys (`REQ-001`, `REQ-002`) if none found
5. Deduplicates against previously ingested requirements
6. Embeds each requirement and stores in Postgres + Qdrant

**Why it exists:** Requirements come in many formats. This normalizes them all into a uniform `(req_key, text)` structure.

---

### `vector_store.py` (152 lines)

**What:** Qdrant vector database interface.

**Key operations:**
- `upsert_requirements()` / `upsert_code_units()` — store embeddings with metadata
- `search_code_units()` — cosine similarity search for a query vector
- `delete_*()` — cleanup per project

**Why it exists:** Isolates all Qdrant-specific code. If you swap to a different vector DB (Pinecone, Weaviate), you only change this file.

---

### `storage.py` (84 lines)

**What:** SQLAlchemy ORM models for Postgres.

**Tables:**
- `requirements_v2` — requirement records (project_id, req_key, text, source_doc)
- `code_units_v2` — code unit records (file_path, symbol, start_line, content)
- `trace_links_v2` — trace links (requirement → code_unit, score, rank, label)

**Why it exists:** Defines the relational schema. Qdrant stores vectors for search; Postgres stores structured records for display, joins, and reporting.

---

### `settings.py` (35 lines)

**What:** Pydantic settings model that reads `.env` configuration.

**Why it exists:** Single source of truth for all config values. Every module imports from here instead of reading env vars directly.

---

### `evaluation.py` (358 lines)

**What:** Computes information retrieval metrics against a gold standard.

**Metrics computed:**
- Precision@k, Recall@k, F1@k
- nDCG@k (normalized discounted cumulative gain)
- Hit@k (did we find ≥1 correct file?)
- MRR (mean reciprocal rank)
- MAP (mean average precision)

**Why it exists:** This is how we measure if the system actually works. Without evaluation, we're guessing.

---

## Scripts — `scripts/`

### `run_api.py` (19 lines)

**What:** Starts the FastAPI server with uvicorn + hot-reload.

**Why it exists:** Convenience entry point. `python3 scripts/run_api.py` is cleaner than remembering the uvicorn command.

---

### `run_benchmark.py` (340 lines)

**What:** End-to-end iTrust benchmark runner.

**Steps:**
1. Converts iTrust raw data into TraceAI format (requirements CSV + gold links CSV)
2. Uploads requirements via the API
3. Ingests the iTrust Java code repository
4. Generates trace links
5. Runs evaluation against the gold standard
6. Prints formatted results table

**Why it exists:** One command to reproduce all benchmark numbers: `python3 scripts/run_benchmark.py`

---

### `generate_charts.py` (257 lines)

**What:** Generates matplotlib charts from evaluation results.

**Charts produced:**
- Aggregate metrics bar chart
- Per-requirement F1 horizontal bars
- Hit/miss pie chart
- Recall distribution histogram
- Precision vs recall scatter
- MRR by gold link count

**Why it exists:** Visual evidence for the research report.

---

## Frontend — `frontend/src/app/`

### `page.tsx` (667 lines)

**What:** The entire UI in a single React component.

**Sections:**
1. **Input form** — project ID, file upload, repo path
2. **Stats cards** — requirements count, code units, trace links, implementation %, avg score
3. **Trace matrix table** — rows with requirement, best match, score, status
4. **Detail modal** — click a row to see matched code + all ranked links

**Why single file:** It's a focused tool, not a multi-page app. One file keeps it simple.

---

### `layout.tsx` (~30 lines)

**What:** Root layout with Inter font + metadata.

---

### `globals.css` (~200 lines)

**What:** CSS custom properties (design tokens) + base styles. Dark theme with HSL color tokens.

---

## Config Files

| File | Purpose |
|------|---------|
| `.env.example` | Template for environment variables |
| `requirements.txt` | Python dependencies |
| `infra/docker-compose.yml` | Postgres + Qdrant containers |
| `.gitignore` | Git exclusion rules |

---

## Data Flow Summary

```
Requirements Doc → requirements_ingestion.py → Postgres + Qdrant (vectors)
Code Repository  → repo_ingestion.py         → Postgres + Qdrant (vectors)
                                                        │
                                              persistence.py (search_and_trace)
                                                        │
                                    ┌───────────────────┼──────────────────┐
                                    ▼                   ▼                  ▼
                              Semantic Search    BM25 Keyword       Query Expansion
                              (Qdrant)          (bm25_index.py)    (E-type flows)
                                    │                   │
                                    └─────────┬─────────┘
                                              ▼
                                    RRF Merge (top 80 chunks)
                                              │
                                              ▼
                                    Cross-Encoder Reranker
                                    (reranker.py)
                                              │
                                              ▼
                                    File-Level Aggregation
                                    (max score per file)
                                              │
                                              ▼
                                    Trace Links → Postgres
                                              │
                                              ▼
                                    Trace Matrix → API → UI
```
