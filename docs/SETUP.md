# Development Setup

## Prerequisites

| Tool | Version | Check |
|------|---------|-------|
| Python | 3.9+ | `python3 --version` |
| Node.js | 18+ | `node --version` |
| Docker | Any | `docker --version` |
| Docker Compose | Any | `docker compose version` |

---

## 1. Infrastructure

```bash
docker compose -f infra/docker-compose.yml up -d

# Verify both services are healthy
docker compose -f infra/docker-compose.yml ps
```

| Service | Port | Dashboard |
|---------|------|-----------|
| PostgreSQL | 5434 | — |
| Qdrant | 6333 | http://localhost:6333/dashboard |

---

## 2. Backend

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Configure environment
cp .env.example .env
```

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TRACEAI_DATABASE_URL` | Yes | `postgresql+psycopg://traceai:traceai@localhost:5434/traceai` | Postgres connection string |
| `TRACEAI_QDRANT_URL` | Yes | `http://localhost:6333` | Qdrant vector database URL |
| `TRACEAI_VECTOR_SIZE` | No | `768` | Embedding dimensions (768 for BAAI, 768 for Gemini) |
| `TRACEAI_EMBEDDING_PROVIDER` | No | `local` | `local`, `huggingface`, `gemini`, or `hash` |
| `HF_TOKEN` | If provider=huggingface | — | HuggingFace API token |
| `GEMINI_API_KEY` | If provider=gemini or using Explainer | — | Google AI Studio Key (Required for explanations and Gemini embeddings) |
| `TRACEAI_EXPLAINER_MODEL` | No | `gemini-2.5-flash` | Gemini model used to generate trace explanations |

### Start

```bash
source .venv/bin/activate
python3 scripts/run_api.py
# API runs on http://localhost:8100
```

Health check:
```bash
curl http://localhost:8100/health
```

---

## 3. Frontend

```bash
cd frontend
npm install
npm run dev
# UI runs on http://localhost:3000
```

---

## 4. Using the UI

1. Enter a **Project ID** (e.g., `my-project`).
2. Upload a **Requirements Document** (PDF, DOCX, TXT, or MD).
3. Enter the **Code Repository** local path.
4. Click **Analyze Traceability**.
5. View the Traceability Matrix showing implementation status and confidence.
6. Click any row to expand details, see matching code units, and lazily load natural language trace explanations.
7. Click **Export Report** to download the analysis as a PDF or CSV file.
8. When files change, inspect the **Impact Analysis** tab to check risk and blast radius.

---

## 5. API Reference

Base URL: `http://localhost:8100`

### Projects

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET`  | `/api/projects` | List all projects |
| `POST` | `/api/projects` | Create a new project |
| `PATCH`| `/api/projects/{project_id}` | Update project metadata |
| `DELETE`| `/api/projects` | Reset and remove all project structures |
| `POST` | `/api/projects/{project_id}/reset` | Reset project analysis records, links, and vectors |
| `POST` | `/api/projects/{project_id}/sync` | Clone or pull code from GitHub and sync changes incrementally |

### Requirements

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/projects/{project_id}/requirements/upload` | Upload requirements document (multipart/form-data) |
| `GET`  | `/api/projects/{project_id}/requirements` | List requirements in the database |

### Code Units

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/projects/{project_id}/repo/ingest` | Process AST code chunks from repo path (`{"repo_path": "/path"}`) |
| `GET`  | `/api/projects/{project_id}/code-units` | List processed code units |
| `GET`  | `/api/projects/{project_id}/vector-stats` | Get collection statistics from Qdrant |

### Trace Links & Runs

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/projects/{project_id}/trace-links/generate` | Generate trace links using hybrid RRF |
| `GET`  | `/api/projects/{project_id}/trace-matrix` | Retrieve the structured trace matrix (including gold standard evaluation if present) |
| `GET`  | `/api/projects/{project_id}/runs` | List execution history and analysis runs |

### Explanations, Impacts & Exports

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET`  | `/api/projects/{project_id}/runs/{run_id}/requirements/{req_id}/explanation` | Fetch or generate RAG explanation for trace link |
| `GET`  | `/api/projects/{project_id}/runs/{run_id}/export/csv` | Download project run metrics as CSV |
| `GET`  | `/api/projects/{project_id}/runs/{run_id}/export/pdf` | Download project run metrics as PDF |
| `GET`  | `/api/projects/{project_id}/impact` | Analyze code file impact score and affected requirements |

---

## 6. Embedding Providers

Edit `.env` to switch embedding providers:

```bash
# Local (default, free, no API key needed)
TRACEAI_EMBEDDING_PROVIDER=local

# HuggingFace Inference API
TRACEAI_EMBEDDING_PROVIDER=huggingface
HF_TOKEN=your_token_here

# Google Gemini
TRACEAI_EMBEDDING_PROVIDER=gemini
GEMINI_API_KEY=your_key_here
```

---

## 7. Troubleshooting

| Problem | Solution |
|---------|----------|
| `401 Unauthorized` from HF | Get a free token from https://huggingface.co/settings/tokens |
| `429 RESOURCE_EXHAUSTED` | Check Gemini limits, or switch to the `local` provider |
| CORS errors in browser | Ensure the backend runs on port 8100 |
| `Dimension mismatch` | Reset the project — collections will automatically re-create with the correct size |
| `Gemini explainer unavailable` | Check that `GEMINI_API_KEY` is correctly defined in `.env` |
| Slow code parsing | Tree-sitter handles parsing sequentially. Large projects may take longer on initial runs |
| DB connection issues | Verify that docker compose is active: `docker compose -f infra/docker-compose.yml ps` |
