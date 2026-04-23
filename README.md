# TraceAI V2

Automated requirements-to-code traceability using semantic embeddings, hybrid retrieval, and cross-encoder reranking.

## What It Does

Upload a requirements document + point to a code repository → TraceAI generates a traceability matrix showing which code files implement each requirement, with confidence scores and implementation status.

## Architecture

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
           Reciprocal Rank Fusion
                     │
                     ▼
           Multi-Chunk Cross-Encoder Reranking
           (ms-marco-MiniLM-L-6-v2)
                     │
                     ▼
           File-Level Aggregation (max score)
                     │
                     ▼
              Trace Matrix + UI
```

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Backend | FastAPI (Python 3.9+) |
| Frontend | Next.js 15 |
| Relational DB | PostgreSQL |
| Vector DB | Qdrant |
| Code Parser | Tree-sitter |
| Embeddings | BAAI/bge-base-en-v1.5 (local) |
| Reranker | cross-encoder/ms-marco-MiniLM-L-6-v2 |

## Quick Start

```bash
# 1. Start databases
docker compose -f infra/docker-compose.yml up -d

# 2. Backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # update the keys (if any)
python3 scripts/run_api.py

# 3. Frontend
cd frontend && npm install && npm run dev
```

Open http://localhost:3000

## Documentation

| Document | Description |
|----------|-------------|
| [Development Setup](docs/SETUP.md) | Full local setup, configuration, API reference, troubleshooting |
| [Evaluation Guide](docs/EVALUATION.md) | Benchmark evaluation, metrics, reproducing results for research report |

## Ports

| Service | Port |
|---------|------|
| Frontend | http://localhost:3000 |
| API | http://localhost:8100 |
| PostgreSQL | localhost:5434 |
| Qdrant | http://localhost:6333 |

## Project Structure

```
traceai_v2/
├── src/traceai_v2/          # Core backend modules
│   ├── api.py               # FastAPI endpoints
│   ├── persistence.py       # Trace link generation pipeline
│   ├── reranker.py          # Cross-encoder reranking
│   ├── bm25_index.py        # BM25 keyword search
│   ├── embeddings.py        # Embedding providers
│   ├── repo_ingestion.py    # Code repository parsing
│   ├── requirements_ingestion.py  # Requirements parsing
│   ├── vector_store.py      # Qdrant interface
│   └── storage.py           # SQLAlchemy models
├── scripts/
│   ├── run_api.py           # Start API server
│   ├── run_benchmark.py     # Run iTrust benchmark evaluation
│   └── generate_charts.py   # Generate evaluation charts
├── frontend/                # Next.js UI
├── data/benchmarks/iTrust/  # iTrust benchmark dataset
└── infra/docker-compose.yml # Postgres + Qdrant
```
