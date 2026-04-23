# TraceAI V2 — Local Setup & Testing Guide

## Prerequisites

| Tool | Version | Check |
|------|---------|-------|
| Python | 3.9+ | `python3 --version` |
| Node.js | 18+ | `node --version` |
| Docker | Any | `docker --version` |
| Docker Compose | Any | `docker compose version` |

---

## 1. Infrastructure (Postgres + Qdrant)

```bash
# Start databases
docker compose up -d

# Verify
docker compose ps
# Should show: postgres (port 5434) + qdrant (port 6333) both healthy
```

---

## 2. Backend Setup

```bash
# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp .env.example .env
# Edit .env — paste your HF_TOKEN (get from https://huggingface.co/settings/tokens)
```

### Environment Variables (.env)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TRACEAI_DATABASE_URL` | Yes | `postgresql+psycopg://traceai:traceai@localhost:5434/traceai` | Postgres connection |
| `TRACEAI_QDRANT_URL` | Yes | `http://localhost:6333` | Qdrant vector DB |
| `TRACEAI_VECTOR_SIZE` | No | `768` | Embedding dimensions |
| `TRACEAI_EMBEDDING_PROVIDER` | No | `huggingface` | `huggingface`, `gemini`, or `hash` |
| `HF_TOKEN` | Yes (if using HF) | — | Free token from HuggingFace |
| `GEMINI_API_KEY` | Only if provider=gemini | — | Google AI Studio key |

### Start Backend

```bash
source .venv/bin/activate
python3 scripts/run_api.py
# Runs on http://localhost:8100
```

---

## 3. Frontend Setup

```bash
cd frontend
npm install
npm run dev
# Runs on http://localhost:3000
```

---

## 4. Manual Testing Workflow

### Step 1: Upload Requirements

1. Open http://localhost:3000
2. In the **Requirements** section, click "Choose File"
3. Select a requirements document (PDF, DOCX, TXT, or MD)
   - Sample: `data/raw/requirements/demo-project/sample_requirements.csv` (if available)
   - Or any text file with numbered requirements
4. Click **"Upload & Index"**
5. Status bar should show: `Requirements: X requirements indexed`

### Step 2: Parse & Index Repository

1. In the **Code** section, enter the repository path
   - Example: `/Users/salmannajah/Developer/trace-ai`
2. Click **"Parse & Index"**
3. Watch the elapsed timer — expect 5-30s depending on repo size
4. Status should show: `Code: X code units indexed`

### Step 3: Generate Trace Links

1. Click **"Generate Trace Matrix"**
2. The trace matrix table should appear with:
   - Requirement text
   - Best linked code unit
   - Similarity score (0.0–1.0)
   - Status label (Implemented / Partial / Missing)
3. Click "View links (5)" to expand all links for a requirement

### Step 4: Run Evaluation (CLI)

```bash
source .venv/bin/activate

# Run against gold standard
python3 scripts/run_evaluation.py

# With custom options
python3 scripts/run_evaluation.py \
  --gold docs/gold_links_demo.csv \
  --project demo-project \
  --k 5 \
  --notes "My test run"

# Output: formatted table + docs/eval_results_demo-project.json
```

---

## 5. API Endpoints Reference

Base URL: `http://localhost:8100`

### Requirements
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/projects/{id}/requirements/upload` | Upload requirements file (multipart form) |
| `GET` | `/api/projects/{id}/requirements` | List all requirements |

### Code
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/projects/{id}/repo/ingest` | Parse repository (`{"repo_path": "/path"}`) |
| `GET` | `/api/projects/{id}/code-units?limit=100` | List code units |

### Traceability
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/projects/{id}/trace-links/generate` | Generate trace links (`{"top_k": 5}`) |
| `GET` | `/api/projects/{id}/trace-matrix` | Get full trace matrix |

### Utilities
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/projects/{id}/vector-stats` | Vector store statistics |
| `POST` | `/api/projects/{id}/reset` | Reset all project data |

### Example: Full flow via curl

```bash
# 1. Upload requirements
curl -X POST http://localhost:8100/api/projects/demo-project/requirements/upload \
  -F "file=@path/to/requirements.csv"

# 2. Parse repository
curl -X POST http://localhost:8100/api/projects/demo-project/repo/ingest \
  -H "Content-Type: application/json" \
  -d '{"repo_path": "/path/to/repo"}'

# 3. Generate trace links
curl -X POST http://localhost:8100/api/projects/demo-project/trace-links/generate \
  -H "Content-Type: application/json" \
  -d '{"top_k": 5}'

# 4. View trace matrix
curl -s http://localhost:8100/api/projects/demo-project/trace-matrix | python3 -m json.tool

# 5. Reset (start fresh)
curl -X POST http://localhost:8100/api/projects/demo-project/reset
```

---

## 6. End-to-End Validation Flow

### Data Flow

```
Requirements Doc (.csv/.pdf/.txt)     Repository (/path/to/repo)
        │                                      │
        ▼                                      ▼
  Upload & Embed                     Tree-sitter Parse & Embed
  (HF bge-base-en-v1.5)            (AST → code units → vectors)
        │                                      │
        ▼                                      ▼
   Qdrant: requirements_v2              Qdrant: code_units_v2
        │                                      │
        └──────────┐    ┌──────────────────────┘
                   ▼    ▼
             Vector Similarity Search
             (cosine, top-k per requirement)
                     │
                     ▼
              Predicted Trace Links
              (req_key → code_key, score)
                     │
          ┌──────────┴──────────┐
          ▼                     ▼
   Gold Standard CSV       Trace Matrix UI
   (human-annotated)       (frontend display)
          │                     
          ▼                     
    Evaluation Metrics          
    (P@k, R@k, F1, MRR, MAP)
```

### Step-by-Step: Creating Gold Standard from Scratch

The gold standard is **human-annotated** ground truth. YOU decide which code units
correctly implement each requirement. Here's how:

#### Option A: Interactive Annotation Tool (Recommended)

```bash
source .venv/bin/activate

# First: make sure you have requirements uploaded, code parsed,
# and trace links generated (Steps 1-3 above)

# Then run the annotation helper:
python3 scripts/annotate_gold.py --project demo-project --output docs/gold_links_demo.csv
```

This tool:
1. Shows you each requirement
2. Shows the predicted code matches (with file path, function name, code preview)
3. You type `1` (fully relevant), `0.5` (partially), or Enter (skip) for each
4. Outputs the annotated gold links CSV

#### Option B: Manual CSV Creation

1. List all code units:
```bash
curl -s "http://localhost:8100/api/projects/demo-project/code-units?limit=500" | \
  python3 -c "import sys,json; [print(f'{u[\"code_key\"]}: {u[\"file_path\"]}::{u[\"symbol\"]}') for u in json.load(sys.stdin)]"
```

2. For each requirement, find the code units that implement it
3. Create `docs/gold_links_demo.csv`:
```csv
req_key,code_key,relevance
REQ-001,CODE-010,1.0
REQ-001,CODE-084,1.0
REQ-002,CODE-119,1.0
```

- `relevance = 1.0`: Code unit directly implements the requirement
- `relevance = 0.5`: Code unit is partially related (data model, helper function)

### Running Evaluation Against Gold Standard

```bash
# Basic run
python3 scripts/run_evaluation.py

# Custom options
python3 scripts/run_evaluation.py \
  --gold docs/gold_links_demo.csv \
  --project demo-project \
  --k 5 \
  --notes "Baseline: HF bge-base + tree-sitter"
```

**Output (terminal):**
```
============================================================
  TraceAI Evaluation Results (k=5)
============================================================
  Precision@5:         0.1500
  Recall@5:            0.1625
  F1@5:               0.1556
  MRR:                  0.3125
  Coverage:             75.0%
============================================================
```

**Output (file):** `docs/eval_results_demo-project.json`

### Full E2E Validation Checklist

```
[ ] 1. Start infrastructure:       docker compose up -d
[ ] 2. Start backend:              python3 scripts/run_api.py
[ ] 3. Start frontend:             cd frontend && npm run dev
[ ] 4. Upload requirements:        (UI or curl)
[ ] 5. Parse repository:           (UI or curl)
[ ] 6. Generate trace links:       (UI or curl)
[ ] 7. Verify in UI:               Check trace matrix scores & labels
[ ] 8. Annotate gold standard:     python3 scripts/annotate_gold.py
[ ] 9. Run evaluation:             python3 scripts/run_evaluation.py
[ ] 10. Check results:             cat docs/eval_results_demo-project.json
```

---

## 7. Switching Embedding Providers

Edit `.env`:

```bash
# Option 1: HuggingFace (default, free, recommended)
TRACEAI_EMBEDDING_PROVIDER=huggingface
HF_TOKEN=your_token_here

# Option 2: Google Gemini (100 req/min free tier)
TRACEAI_EMBEDDING_PROVIDER=gemini
GEMINI_API_KEY=your_key_here

# Option 3: Hash fallback (offline, low quality, for testing only)
TRACEAI_EMBEDDING_PROVIDER=hash
```

After changing provider: restart the API, reset the project, and re-ingest everything.

---

## 8. Troubleshooting

| Problem | Solution |
|---------|----------|
| `401 Unauthorized` from HF | Get a free token from https://huggingface.co/settings/tokens |
| `429 RESOURCE_EXHAUSTED` from Gemini | Wait 60s, or switch to `huggingface` provider |
| CORS errors in browser | Ensure backend runs on port 8100 (not 8000) |
| `Dimension mismatch` | Reset project — vector store auto-recreates collections |
| Slow code parsing | Normal for large repos — watch elapsed timer. Batch embedding reduces API calls |
| `No route to host` | Check Docker is running: `docker compose ps` |
