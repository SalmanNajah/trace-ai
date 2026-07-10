# TraceAI

Automated requirements-to-code traceability using hybrid semantic/keyword retrieval, cross-encoder reranking, and RAG-based natural language trace explanations.

---

## Key Features

- 🔍 **Hybrid Retrieval**: Combines local semantic embeddings (BAAI/bge-base-en-v1.5) or cloud models (Gemini) with BM25 keyword matching using Reciprocal Rank Fusion (RRF).
- 🚀 **Multi-Chunk Reranking**: Scores AST chunks individually using a cross-encoder (`ms-marco-MiniLM-L-6-v2`) and aggregates scores to the file level using a max-pool operation.
- 🤖 **RAG-Based Trace Explanations**: Automatically retrieves the target requirement text and matching code snippet, generating a clear natural language explanation of how the code implements the requirement using Gemini (`gemini-2.5-flash`), with SQLite/Postgres caching.
- ⚡ **Impact Analysis**: Automatically calculates risk levels (Low, Medium, High) and blast radius requirements when source files are modified.
- 🔄 **Git Integration & Incremental Sync**: Incremental git-diff syncing allows the system to update code units and vector embeddings only for modified files, keeping indexing fast.
- 📊 **IEEE-Compliant Evaluation**: Automatically computes MRR, Hit@k, NDCG@k, MAP, Precision, Recall, and F1-score when a solution gold standard is present.
- 📄 **Report Exporting**: Exports reports to professionally styled PDF summaries (using ReportLab) or standard CSV files.
- 🎨 **Dynamic Dashboard**: Beautiful dark-mode dashboard (Next.js 15) complete with mapping quality breakdowns, coverage statistics, evaluation charts, and interactive trace detail drawers.

---

## Retrieval & RAG Architecture

TraceAI implements a Retrieval-Augmented Generation (RAG) pipeline to bridge the semantic gap between natural language requirements and source code logic.

```
Requirements (.pdf/.docx/.txt)          Code Repository (local path)
        │                                         │
        ▼                                         ▼
  Parse & Embed                          Tree-sitter AST Parse & Embed
  (BAAI/bge-base-en-v1.5)               (functions, classes, methods)
        │                                         │
        ▼                                         ▼
   Qdrant: requirements                    Qdrant: code_units
        │                                         │
        └────────────┐      ┌─────────────────────┘
                     ▼      ▼
            Hybrid Retrieval (Semantic + BM25)
            Reciprocal Rank Fusion (RRF)
                     │
                     ▼
            Multi-Chunk Cross-Encoder Reranking
            (ms-marco-MiniLM-L-6-v2)
                     │
                     ▼
            File-Level Aggregation (max score)
                     │
                     ▼
            Trace Links (SQL DB) ──► Impact Analysis
                     │
                     ▼
         ┌───────────────────────────────┐
         │ RAG Explainability Pipeline   │◄── On-Demand Explanation Request
         │                               │
         │  1. Retrieve: Requirement text│
         │               + Code Snippet  │
         │  2. Prompt: Context synthesis │
         │  3. LLM: gemini-2.5-flash     │
         │  4. Cache: Save explanation   │
         └───────────────┬───────────────┘
                         │
                         ▼
                Trace Matrix + UI
```

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| **Backend** | FastAPI (Python 3.9+) |
| **Frontend** | Next.js 15, React, Tailwind CSS |
| **Relational DB** | PostgreSQL (SQLAlchemy ORM) |
| **Vector DB** | Qdrant |
| **AST Parser** | Tree-sitter |
| **Embeddings** | BAAI/bge-base-en-v1.5 (local via sentence-transformers) or Gemini |
| **Reranker** | cross-encoder/ms-marco-MiniLM-L-6-v2 |
| **LLM / Explainer** | Google Gemini (`gemini-2.5-flash` via `google-genai` SDK) |
| **Reporting** | ReportLab (PDF), CSV |
| **Evaluation Charts** | Matplotlib |

---

## Quick Start

### 1. Spin up Infrastructure
Start PostgreSQL and Qdrant database engines:
```bash
docker compose -f infra/docker-compose.yml up -d
```

### 2. Set Up Backend
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # Update GEMINI_API_KEY and other settings as needed
python3 scripts/run_api.py
```
*The API server will run at http://localhost:8100*

### 3. Set Up Frontend
```bash
cd frontend
npm install
npm run dev
```
*The dashboard will run at http://localhost:3000*

---

## Project Structure

```
traceai_v2/
├── src/traceai_v2/            # Core backend modules
│   ├── api.py                 # FastAPI endpoints
│   ├── persistence.py         # Trace link and impact analysis generation
│   ├── explainer.py           # Gemini RAG explanation generator
│   ├── github_integration.py  # Repository Git manager and branch cloner
│   ├── reranker.py            # Cross-encoder reranking
│   ├── bm25_index.py          # BM25 keyword search indexer
│   ├── embeddings.py          # Embedding providers (local, HF, Gemini)
│   ├── repo_ingestion.py      # Code repository parser (Tree-sitter AST)
│   ├── requirements_ingestion.py # Requirements parser (PDF/DOCX/TXT/MD)
│   ├── vector_store.py        # Qdrant client wrapper
│   ├── storage.py             # SQLAlchemy Postgres models
│   ├── report_export.py       # PDF/CSV report generation logic
│   └── settings.py            # Env configuration loader
├── scripts/
│   ├── run_api.py             # Start API server
│   ├── run_benchmark.py       # Run iTrust benchmark dataset evaluation
│   ├── run_perf_benchmark.py  # Run throughput performance benchmark script
│   └── generate_charts.py     # Generate evaluation graphs/charts
├── frontend/                  # Next.js UI Application
│   ├── src/app/page.tsx       # Main trace dashboard interface
│   ├── src/lib/tracing.ts     # Client scoring, mapping and clamping helpers
│   └── src/app/layout.tsx     # Next.js layout configuration
├── data/benchmarks/iTrust/    # iTrust benchmark solution files
└── infra/docker-compose.yml   # Docker compose configuration (Postgres + Qdrant)
```

---

## Port Mappings

| Service | Address |
|---------|---------|
| Frontend UI | [http://localhost:3000](http://localhost:3000) |
| API Docs (Swagger) | [http://localhost:8100/docs](http://localhost:8100/docs) |
| PostgreSQL | localhost:5434 |
| Qdrant Dashboard | [http://localhost:6333/dashboard](http://localhost:6333/dashboard) |

---

## Detailed Documentation

To dive deeper into setup, architecture, and evaluations:
* ⚙️ **[Development Setup](docs/SETUP.md)**: Full local setup, environment configuration, and backend API reference.
* 🏗️ **[Architecture Details](docs/ARCHITECTURE.md)**: Exhaustive breakdown of code parser AST chunking, pipeline flows, and data representations.
* 📊 **[Evaluation & Benchmarks](docs/EVALUATION.md)**: Metrics overview, iTrust dataset structure, and reproducing research results.
