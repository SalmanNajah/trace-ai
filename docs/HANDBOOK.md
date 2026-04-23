# TraceAI V2 Handbook

This is the main guide for setup, run, test, and understanding flow.

## 1) What is this build
Current build has:
1. Requirements ingestion (`pdf`, `docx`, `txt`, `md`)
2. Local repo parsing (Python, JS, TS)
3. Storage in Postgres
4. Vector indexing in Qdrant
5. Traceability link generation
6. Traceability matrix + completion %
7. Minimal Next.js UI

## 2) Ports
1. Frontend: `http://localhost:3000`
2. API: `http://localhost:8100`
3. Postgres: `localhost:5434`
4. Qdrant HTTP: `localhost:6333`
5. Qdrant gRPC: `localhost:6334`

## 3) Very simple flow
1. User uploads requirement file.
2. API parses text into requirement chunks.
3. Chunks are stored in Postgres (`requirements_v2`).
4. Same chunks are embedded and stored in Qdrant (`requirements_v2` collection).
5. User gives local repo path.
6. API parses code units (function/class/file chunks).
7. Code units are stored in Postgres (`code_units_v2`).
8. Same code units are embedded and stored in Qdrant (`code_units_v2` collection).
9. User clicks `Generate Matrix`.
10. System retrieves top-k code candidates for each requirement.
11. System writes trace links in Postgres (`trace_links_v2`).
12. UI shows matrix + linked code + completion %.

## 4) Why both Postgres and Qdrant
1. Postgres stores structured records for display, joins, reporting.
2. Qdrant stores vectors for semantic similarity search.
3. This is not duplicate waste. They serve different jobs.

## 5) What does `Vectors X / Y` mean
1. `X` = number of requirement vectors for current project.
2. `Y` = number of code-unit vectors for current project.

Example:
`20 / 681` means:
1. 20 requirement embeddings
2. 681 code-unit embeddings

## 6) Why numbers were increasing before
Earlier, re-ingest was appending.
Now fixed: re-ingest for same `project_id` replaces old project data (Postgres + Qdrant) before new insert.

## 7) Setup steps
### Backend
```bash
cd /Users/salmannajah/Developer/trace-ai/traceai_v2
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
docker compose -f infra/docker-compose.yml up -d
python3 scripts/run_api.py
```

Health:
```bash
curl http://localhost:8100/health
```

### Frontend
```bash
cd /Users/salmannajah/Developer/trace-ai/traceai_v2/frontend
cp .env.example .env.local
npm install
npm run dev
```

## 8) UI usage
1. Set `Project` (example: `demo-project`)
2. Upload requirement file and click `Upload & Ingest`
3. Set repo path and click `Parse & Index`
4. Click `Generate Matrix`
5. Open `View links` per requirement row to inspect linked code evidence

## 9) API quick reference
1. `POST /api/projects/{project_id}/requirements/upload`
2. `POST /api/projects/{project_id}/repo/ingest`
3. `POST /api/projects/{project_id}/trace-links/generate`
4. `GET /api/projects/{project_id}/trace-matrix`
5. `GET /api/projects/{project_id}/vector-stats`
6. `GET /api/projects/{project_id}/vectors/sample?kind=requirements|code_units&limit=3`
7. `POST /api/projects/{project_id}/reset`

## 10) How to inspect actual vectors
### From API (recommended)
```bash
curl "http://localhost:8100/api/projects/demo-project/vectors/sample?kind=requirements&limit=2"
curl "http://localhost:8100/api/projects/demo-project/vectors/sample?kind=code_units&limit=2"
```

This returns:
1. vector id
2. payload metadata
3. vector size
4. first few dimensions (`vector_preview`)

### From Qdrant directly    
```bash
curl http://localhost:6333/collections
```
Dashboard:
`http://localhost:6333/dashboard`

## 12) Known scope limit
Current code ingestion is local path based.
GitHub App flow is intentionally deferred to later pack.

