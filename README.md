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

---

## Benchmark Datasets & Manual Execution Guide

TraceAI supports IEEE-compliant scientific benchmarking across multiple languages and datasets:
1. **iTrust (Java)**: Medical EHR system (132 requirements, 19 Java files, 276 gold links).
2. **LibEST (C)**: RFC 7030 Enrollment over Secure Transport (52 requirements, 14 C files, 204 gold links).

### 1. Data Directory Structure (`data/`)

```
data/
├── repos/                   # Cloned Git repositories (GitHub integration)
├── raw/uploads/             # User-uploaded requirements files (PDF, DOCX, TXT)
├── interim/                 # Staging tables before DB/Vector insertion
│   ├── code_units/          # Extracted Tree-sitter AST chunks (.csv)
│   └── requirements/        # Extracted normalized requirement chunks (.csv, .txt)
├── processed/projects/      # Consolidated project outputs & cached indices
└── benchmarks/              # Peer-reviewed scientific ground-truth datasets
    ├── iTrust/              # Java EHR Benchmark
    └── LibEST/              # C RFC 7030 Benchmark
```

Each benchmark folder contains:
- `code/`: Source code files under evaluation (`.java` or `.c`/`.h`).
- `req/`: Individual raw requirement text files.
- `requirements_<dataset>.csv`: Cleaned structured table of requirements.
- `gold_links_<dataset>.csv`: Human-annotated ground-truth links mapping requirements to implementing code files.
- `eval_results_<dataset>.json`: Empirical benchmark evaluation results.

### 2. Metric Definitions & Intuition

#### Information Retrieval (IR) Metrics ($k=10$)
- **Hit@10 (Requirement Success Rate)**: The percentage of requirements for which at least *one* correct implementing file was retrieved in the top 10 results. In practice, this measures whether the developer gets a useful starting point for their task.
- **Recall@10 (Code Completeness)**: The proportion of all true ground-truth trace links that were captured within the top 10 recommendations. High recall ensures that developers and auditors do not miss critical implementation files.
- **Precision@10 (Result Purity)**: The fraction of top-10 recommended files that are valid ground-truth implementations.
- **F1@10**: The harmonic mean of Precision@10 and Recall@10, providing a balanced measure of retrieval accuracy.
- **MRR (Mean Reciprocal Rank)**: $\frac{1}{|Q|}\sum \frac{1}{\text{rank}_1}$, measuring where the *first* correct file appears. If the first correct file is at rank 1, score is $1.0$; if at rank 2, score is $0.5$; if at rank 3, $0.33$. Higher MRR means less scrolling and manual inspection for the developer.
- **nDCG@10 (Ranking Quality)**: Normalized Discounted Cumulative Gain. Unlike Hit@10 which treats any rank in the top 10 equally, nDCG rewards placing relevant files higher in the list and penalizes relevant files placed lower down.
- **MAP (Mean Average Precision)**: The average of precision scores computed at each position where a relevant file is retrieved, evaluating overall ranking precision across all recall levels.

#### RAG Explanation Quality Metrics ($N=30$ audited links per dataset)
- **Code Faithfulness (%)**: The percentage of code identifiers (methods, functions, classes, and variables) cited in Gemini's generated explanation that actually exist inside the target repository files. Verifies that the model references real code.
- **Entity Hallucination Rate (%)**: The percentage of generated explanations that contain at least one fabricated, non-existent, or unverified code identifier.
- **Factuality Score (1–5 Likert Scale)**: Human and LLM-as-a-judge score assessing whether the technical explanation is factually accurate regarding how the code satisfies the requirement.
- **Developer Utility Score (1–5 Likert Scale)**: Assessment of whether the explanation is actionable, clear, and useful for a developer during code review or maintenance.
- **Mean Word Count**: The average length of the generated explanation, measuring conciseness (target: 25–35 words).

### 3. Unified Manual Execution Guide

Ensure the database containers are active:
```bash
docker compose -f infra/docker-compose.yml up -d
```

Set Python path and activate the virtual environment:
```bash
source .venv/bin/activate
export PYTHONPATH=src
```

#### A. Full Benchmark Evaluations ($k=10$)
```bash
# iTrust (Java EHR System):
PYTHONPATH=src .venv/bin/python scripts/run_benchmark.py --dataset itrust --eval-only --k 10

# eTour (Java Tourism GIS System):
PYTHONPATH=src .venv/bin/python scripts/run_benchmark.py --dataset etour --eval-only --k 10

# LibEST (C RFC 7030 Secure Transport):
PYTHONPATH=src .venv/bin/python scripts/run_benchmark.py --dataset libest --eval-only --k 10

# Run all 3 datasets in sequence:
PYTHONPATH=src .venv/bin/python scripts/run_benchmark.py --dataset all --eval-only --k 10
```

#### B. Component Ablation Studies ($k=10$)
```bash
# iTrust Ablation:
PYTHONPATH=src .venv/bin/python scripts/run_ablation.py --dataset itrust --k 10

# eTour Ablation:
PYTHONPATH=src .venv/bin/python scripts/run_ablation.py --dataset etour --k 10

# LibEST Ablation:
PYTHONPATH=src .venv/bin/python scripts/run_ablation.py --dataset libest --k 10

# Run all 3 ablations in sequence:
PYTHONPATH=src .venv/bin/python scripts/run_ablation.py --dataset all --k 10
```

#### C. RAG Trace Explanation Quality Evaluations
```bash
# iTrust Explanations:
PYTHONPATH=src .venv/bin/python scripts/evaluate_explanations.py --dataset itrust --sample-size 30

# eTour Explanations:
PYTHONPATH=src .venv/bin/python scripts/evaluate_explanations.py --dataset etour --sample-size 30

# LibEST Explanations:
PYTHONPATH=src .venv/bin/python scripts/evaluate_explanations.py --dataset libest --sample-size 30

# Run all 3 explanation evaluations:
PYTHONPATH=src .venv/bin/python scripts/evaluate_explanations.py --dataset all --sample-size 30
```

