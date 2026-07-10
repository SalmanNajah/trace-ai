# Evaluation & Performance Guide

This guide describes the evaluation frameworks and performance benchmarking systems in TraceAI.

---

## 1. IEEE-Compliant Evaluation Framework

TraceAI provides a built-in evaluation framework to measure requirements-to-code traceability metrics against a human-annotated gold standard solution.

### Benchmark Dataset: iTrust
TraceAI includes the peer-reviewed **iTrust** traceability benchmark (from ICSME'21):
- **Requirements**: 131 use case flows (UC keys)
- **Code Files**: 241 Java source files
- **Gold Links**: 286 human-annotated file-level trace links
- **Location**: `data/benchmarks/iTrust/`

---

## 2. Dynamic Evaluation in the Dashboard

Evaluation is integrated directly into the Trace Link generation flow. When retrieving the traceability matrix:
1. The backend automatically looks for a gold standard CSV (`gold_links_{project_id}.csv`) using a file path helper (`_find_gold_csv`).
2. If found, the server executes `traceai_v2.evaluation.evaluate` using a `top_k=10` threshold.
3. The server computes the following metrics and returns them directly to the frontend:
   - **Hit@k**: % of requirements with ≥ 1 correct file in the top-k matches (measures overall retrieval coverage).
   - **MRR (Mean Reciprocal Rank)**: Computes the reciprocal rank of the first correct match, averaged over all queries.
   - **nDCG@k (Normalized Discounted Cumulative Gain)**: Measures the quality of the ranked results.
   - **MAP (Mean Average Precision)**: Measures average precision across all requirements.
   - **Precision@k, Recall@k, F1@k**: Standard relevance metrics.
4. The dashboard renders these metrics in real-time on the main screen and shows correctness markers for every individual trace link.

---

## 3. Running the Benchmark

### Full Evaluation Run
To run the iTrust evaluation manually and output the results:
```bash
source .venv/bin/activate

# Ingest iTrust, generate traces, and run evaluation
python3 scripts/run_benchmark.py

# Re-evaluate without re-ingesting (faster, reuses cached embeddings)
python3 scripts/run_benchmark.py --reeval
```

### Visualizing Results
After running the benchmark, generate evaluation charts:
```bash
python3 scripts/generate_charts.py
```
This produces graphs under `data/benchmarks/iTrust/charts/`, including:
- `aggregate_metrics.png` (Bar chart of MAP, MRR, Hit@10)
- `per_requirement_f1.png` (F1 per requirement flow)
- `hit_miss_pie.png` (Hit vs Miss ratio)
- `recall_distribution.png` (Recall score histogram)

---

## 4. Performance & Scalability Benchmarking

TraceAI includes a dedicated benchmarking suite to measure execution times and scale metrics across different volumes of requirements and code files.

### The Benchmarking Script: `run_perf_benchmark.py`
The performance suite runs three experimental scales of the iTrust dataset:
1. **Small**: 25 requirements, 50 code files.
2. **Medium**: 50 requirements, 100 code files.
3. **Full**: All requirements (131) and all code files (241).

### Running the Performance Benchmark
```bash
# Ensure the API server is running on port 8100
python3 scripts/run_perf_benchmark.py
```

### Performance Metrics Captured
The benchmarking script measures the execution time (in seconds) of four distinct operations:
- **Database Reset**: Cleaning out PostgreSQL database tables and Qdrant vector collections.
- **Embed Reqs**: Embedding the requirements document chunk texts and indexing them in Qdrant.
- **Embed Repo**: Parsing repository source files with Tree-sitter AST, chunking contents, and generating/indexing vector embeddings.
- **Trace Generation**: Computing query expansions, vector similarity matches, BM25 indices, RRF merges, cross-encoder rerankings, and file-level aggregations.

### Output Results
Metrics are printed to the console and saved to `data/benchmarks/iTrust/perf_results.csv` for analysis.

---

## 5. Benchmark Performance History

Below are historical benchmarks for the default embedding setup (BAAI/bge-base-en-v1.5 + ms-marco-MiniLM-L-6-v2 reranker):

### Retrieval Quality Progress
| Version | Hit@10 | MRR | MAP | Key Architectural Improvement |
|---------|--------|-----|-----|------------------------------|
| Baseline | 64.8% | 0.395 | 0.210 | Semantic similarity search only |
| + File-level dedup | 65.7% | 0.402 | 0.218 | File-level deduplication prior to reranking |
| + BM25 Hybrid (RRF) | 67.6% | 0.430 | 0.245 | Keyword fusion and Exception flow query expansions |
| + Full File context | 68.6% | 0.445 | 0.258 | Rich filename context in cross-encoder |
| **+ Multi-Chunk Rerank** | **74.3%** | **0.496** | **0.287** | Rerank all AST chunks, then apply Max-Pool per file |

### Baseline Comparison
- **VSM (Vector Space Model)**: ~50% Hit@10
- **LSI (Latent Semantic Indexing)**: ~55% Hit@10
- **LDA (Latent Dirichlet Allocation)**: ~60% Hit@10
- **TraceAI (Current System)**: **74.3%** Hit@10
