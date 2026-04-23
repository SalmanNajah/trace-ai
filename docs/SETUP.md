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
| `TRACEAI_DATABASE_URL` | Yes | `postgresql+psycopg://traceai:traceai@localhost:5434/traceai` | Postgres connection |
| `TRACEAI_QDRANT_URL` | Yes | `http://localhost:6333` | Qdrant vector DB |
| `TRACEAI_VECTOR_SIZE` | No | `768` | Embedding dimensions |
| `TRACEAI_EMBEDDING_PROVIDER` | No | `local` | `local`, `huggingface`, `gemini`, or `hash` |
| `HF_TOKEN` | If provider=huggingface | — | HuggingFace API token |
| `GEMINI_API_KEY` | If provider=gemini | — | Google AI Studio key |

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

1. Enter a **Project ID** (e.g., `my-project`)
2. Upload a **Requirements Document** (PDF, DOCX, TXT, or MD)
3. Enter the **Code Repository** local path
4. Click **Analyze Traceability**
5. Click any row to see matched code and all trace links

---

## 5. API Reference

Base URL: `http://localhost:8100`

### Requirements

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/projects/{id}/requirements/upload` | Upload requirements file (multipart) |
| `GET` | `/api/projects/{id}/requirements` | List all requirements |

### Code

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/projects/{id}/repo/ingest` | Parse repository (`{"repo_path": "/path"}`) |
| `GET` | `/api/projects/{id}/code-units?limit=100` | List code units |

### Traceability

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/projects/{id}/trace-links/generate` | Generate trace links |
| `GET` | `/api/projects/{id}/trace-matrix` | Full trace matrix |

### Utilities

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/projects/{id}/vector-stats` | Vector store statistics |
| `POST` | `/api/projects/{id}/reset` | Reset all project data |

### CLI Example

```bash
# Full flow via curl
curl -X POST http://localhost:8100/api/projects/my-project/requirements/upload \
  -F "file=@requirements.txt"

curl -X POST http://localhost:8100/api/projects/my-project/repo/ingest \
  -H "Content-Type: application/json" \
  -d '{"repo_path": "/path/to/repo"}'

curl -X POST http://localhost:8100/api/projects/my-project/trace-links/generate

curl -s http://localhost:8100/api/projects/my-project/trace-matrix | python3 -m json.tool
```

---

## 6. Embedding Providers

Edit `.env` to switch providers:

```bash
# Local (default, free, no API key needed)
TRACEAI_EMBEDDING_PROVIDER=local

# HuggingFace Inference API
TRACEAI_EMBEDDING_PROVIDER=huggingface
HF_TOKEN=your_token_here

# Google Gemini
TRACEAI_EMBEDDING_PROVIDER=gemini
GEMINI_API_KEY=your_key_here

# Hash fallback (offline, low quality, for testing only)
TRACEAI_EMBEDDING_PROVIDER=hash
```

After switching: restart the API, reset the project, and re-ingest everything.

---

## 7. Troubleshooting

| Problem | Solution |
|---------|----------|
| `401 Unauthorized` from HF | Get a free token from https://huggingface.co/settings/tokens |
| `429 RESOURCE_EXHAUSTED` from Gemini | Wait 60s, or switch to `local` provider |
| CORS errors in browser | Ensure backend runs on port 8100 |
| `Dimension mismatch` | Reset project — collections auto-recreate |
| Slow code parsing | Normal for large repos — watch elapsed timer |
| `No route to host` | Check Docker is running: `docker compose -f infra/docker-compose.yml ps` |
