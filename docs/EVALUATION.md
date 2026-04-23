# Evaluation Guide

End-to-end evaluation of TraceAI against the iTrust benchmark for research reporting.

---

## Benchmark Dataset

**iTrust** is a peer-reviewed requirements-to-code traceability benchmark from the CoEST community (ICSME'21).

| Property | Value |
|----------|-------|
| Requirements | 131 use case flows (UC keys) |
| Code Files | 241 Java source files |
| Gold Links | 286 human-annotated file-level trace links |
| Source | Center of Excellence for Software Traceability |

Data location: `data/benchmarks/iTrust/`

---

## Running the Benchmark

### Prerequisites

1. API server running: `python3 scripts/run_api.py`
2. Infrastructure running: `docker compose -f infra/docker-compose.yml up -d`

### Full Benchmark Run

```bash
source .venv/bin/activate

# Run complete benchmark (ingest + trace + evaluate)
python3 scripts/run_benchmark.py

# Re-evaluate without re-ingesting (faster, reuses embeddings)
python3 scripts/run_benchmark.py --reeval

# Generate visualization charts
python3 scripts/generate_charts.py
```

### Output Files

| File | Description |
|------|-------------|
| `data/benchmarks/iTrust/eval_results_itrust.json` | Full evaluation results (aggregate + per-requirement) |
| `data/benchmarks/iTrust/charts/aggregate_metrics.png` | Bar chart of all metrics |
| `data/benchmarks/iTrust/charts/per_requirement_f1.png` | F1 score per requirement |
| `data/benchmarks/iTrust/charts/hit_miss_pie.png` | Hit vs miss distribution |
| `data/benchmarks/iTrust/charts/recall_distribution.png` | Recall distribution histogram |
| `data/benchmarks/iTrust/charts/precision_recall_scatter.png` | P vs R scatter plot |
| `data/benchmarks/iTrust/charts/mrr_by_gold_count.png` | MRR by number of gold links |

---

## Metrics Reference

### Aggregate Metrics

| Metric | Formula | What It Measures |
|--------|---------|-----------------|
| **Precision@k** | correct in top-k / k | How many retrieved files are relevant |
| **Recall@k** | correct in top-k / total gold | How many relevant files were found |
| **F1@k** | harmonic mean of P and R | Balance of precision and recall |
| **nDCG@k** | normalized discounted cumulative gain | Ranking quality (correct files ranked higher = better) |
| **Hit@k** | % of requirements with ≥1 correct file in top-k | Coverage — did we find at least one match? |
| **MRR** | mean of 1/rank of first correct file | How quickly the first correct file appears |
| **MAP** | mean average precision across requirements | Overall ranking quality |

### Per-Requirement Metrics

Each requirement is evaluated individually with P@k, R@k, F1@k, and RR (reciprocal rank). The per-requirement breakdown identifies specific failure cases.

### Score Labels (for UI)

| Label | Score Range | Meaning |
|-------|------------|---------|
| Implemented | ≥ 0.50 | Strong semantic match |
| Partial | 0.38 – 0.49 | Moderate match |
| Missing | < 0.38 | Weak or no match (not stored) |

---

## Current Results

### Configuration

| Setting | Value |
|---------|-------|
| Embedding Model | BAAI/bge-base-en-v1.5 (local, 768d) |
| Reranker | cross-encoder/ms-marco-MiniLM-L-6-v2 |
| Retrieval | Hybrid (Semantic + BM25, RRF fusion) |
| Reranking | Multi-chunk (80 chunks → aggregate max per file) |
| Code Parser | Tree-sitter |
| k | 10 |

### Aggregate Performance

| Metric | Score |
|--------|-------|
| Precision@10 | 0.124 |
| Recall@10 | 0.483 |
| F1@10 | 0.189 |
| nDCG@10 | 0.391 |
| **Hit@10** | **74.3%** |
| MRR | 0.496 |
| MAP | 0.287 |

### Progress Tracker

| Version | Hit@10 | Key Change |
|---------|--------|-----------|
| Baseline (semantic only) | 64.8% | bge-base + ms-marco reranker |
| + File-level dedup | 65.7% | Deduplicate before reranking |
| + BM25 hybrid + query expansion | 67.6% | RRF fusion, E-type context |
| + Full file context for reranker | 68.6% | Filename + concatenated chunks |
| **+ Multi-chunk reranking** | **74.3%** | Rerank all chunks → max per file |

### Comparison with Published Baselines

| Method | Hit@10 | Source |
|--------|--------|--------|
| VSM (Vector Space Model) | ~50% | CoEST baseline |
| LSI (Latent Semantic Indexing) | ~55% | CoEST baseline |
| LDA (Latent Dirichlet Allocation) | ~60% | CoEST baseline |
| **TraceAI (this system)** | **74.3%** | Current results |
| Fine-tuned BERT models | 80–85% | FTLR (Zhao et al., 2023) |

---

## Remaining Failure Analysis

### Failure Breakdown (27 missed requirements)

| Type | Count | Root Cause |
|------|-------|-----------|
| E-type (exception flows) | 15 | Need `AuthDAO.java` / `GetUserNameAction.java` — cross-cutting auth code with no semantic similarity to individual UC descriptions |
| S-type (success flows) | 10 | Scattered logic across multiple files, weak embedding signal |
| Other | 2 | Edge cases |

### Why 85%+ Requires Model Upgrade

The remaining misses are **fundamentally hard** for a general-purpose English embedding model:

- Requirements like *"The system shall display an error message"* need to map to `AuthDAO.java` — a file about database authentication
- No amount of retrieval engineering can bridge this semantic gap
- Code-specific fine-tuned models (CodeBERT, FTLR) are needed for the next performance tier

---

## Creating Gold Standard for Your Own Projects

### Interactive Annotation

```bash
# After running trace link generation:
python3 scripts/annotate_gold.py --project my-project --output docs/gold_links_myproject.csv
```

The tool shows each requirement with its predicted code matches. You rate each as:
- `1` = fully implements the requirement
- `0.5` = partially related
- Enter = skip (not related)

### Manual CSV

Create a CSV with columns: `req_key,code_identifier`

```csv
req_key,code_identifier
REQ-001,UserService.java
REQ-001,AuthController.java
REQ-002,FileUploader.tsx
```

### Running Evaluation

```bash
python3 scripts/run_evaluation.py \
  --gold docs/gold_links_myproject.csv \
  --project my-project \
  --k 10
```
