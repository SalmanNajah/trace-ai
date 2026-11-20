#!/usr/bin/env python3
"""Unified TraceAI Component Ablation Study Suite.

Evaluates the marginal contribution of each architectural component:
  1. Full TraceAI: AST + BM25 + Dense (BGE) + RRF + Cross-Encoder
  2. w/o Cross-Encoder: AST + BM25 + Dense (BGE) + RRF (Pure rank fusion)
  3. w/o BM25: AST + Dense (BGE) + Cross-Encoder (Dense-only retrieval + rerank)
  4. Lexical BM25 Only: AST + BM25 (Keyword matching only)
  5. Dense Semantic Only: AST + Dense (BGE) (Cosine similarity only)

Usage:
  python3 scripts/run_ablation.py --dataset itrust --k 10
  python3 scripts/run_ablation.py --dataset libest --k 10
  python3 scripts/run_ablation.py --dataset etour --k 10
  python3 scripts/run_ablation.py --dataset all --k 10
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from traceai_v2.bm25_index import BM25Index
from traceai_v2.embeddings import embed_text
from traceai_v2.evaluation import GoldLink, PredictedLink, evaluate
from traceai_v2.persistence import _score_to_label
from traceai_v2.reranker import rerank_candidates, is_available as reranker_available
from traceai_v2.settings import load_settings
from traceai_v2.storage import CodeUnitRecord, RequirementRecord
from traceai_v2.vector_store import VectorCollections, VectorStore

DATASET_CONFIGS = {
    "itrust": {
        "name": "iTrust (Java EHR)",
        "project_id": "itrust-benchmark",
        "dir": PROJECT_ROOT / "data" / "benchmarks" / "iTrust",
        "gold_csv": "gold_links_itrust.csv",
        "has_exceptions": True,
    },
    "libest": {
        "name": "LibEST (C RFC 7030)",
        "project_id": "libest-benchmark",
        "dir": PROJECT_ROOT / "data" / "benchmarks" / "LibEST",
        "gold_csv": "gold_links_libest.csv",
        "has_exceptions": False,
    },
    "etour": {
        "name": "eTour (Java Tourism GIS)",
        "project_id": "etour-benchmark",
        "dir": PROJECT_ROOT / "data" / "benchmarks" / "eTour",
        "gold_csv": "gold_links_etour.csv",
        "has_exceptions": False,
    },
}


def load_gold_links(gold_csv: Path, valid_files: set[str]) -> list[GoldLink]:
    gold_links = []
    with gold_csv.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code_file = row["code_identifier"].strip()
            if code_file in valid_files:
                gold_links.append(GoldLink(
                    req_key=row["req_key"],
                    code_key=code_file,
                    relevance=float(row.get("relevance", "1.0")),
                ))
    return gold_links


def run_ablation_for_dataset(ds_key: str, k: int = 10) -> list[dict]:
    cfg = DATASET_CONFIGS[ds_key]
    project_id = cfg["project_id"]
    bdir = cfg["dir"]

    print("\n" + "=" * 80)
    print(f"  RUNNING COMPONENT ABLATION EXPERIMENTS: {cfg['name']}")
    print(f"  Project ID: {project_id} | Cutoff: k={k}")
    print("=" * 80)

    settings = load_settings()
    engine = create_engine(settings.database_url)

    vs = VectorStore(
        url=settings.qdrant_url,
        collections=VectorCollections(
            requirements=settings.qdrant_requirements_collection,
            code_units=settings.qdrant_code_units_collection,
            size=settings.vector_size,
        )
    )

    with Session(engine) as session:
        requirements = session.scalars(
            select(RequirementRecord)
            .where(RequirementRecord.project_id == project_id)
            .order_by(RequirementRecord.id)
        ).all()

        code_units = session.scalars(
            select(CodeUnitRecord)
            .where(CodeUnitRecord.project_id == project_id)
            .order_by(CodeUnitRecord.id)
        ).all()

    if not requirements or not code_units:
        print(f"Error: No requirements ({len(requirements)}) or code units ({len(code_units)}) found for {project_id}")
        return []

    code_index = {cu.code_unit_id: cu for cu in code_units}
    code_key_to_file = {cu.code_key: Path(cu.file_path).name for cu in code_units}
    valid_files = set(code_key_to_file.values())

    gold_csv = bdir / cfg["gold_csv"]
    gold_links = load_gold_links(gold_csv, valid_files)
    print(f"Loaded {len(requirements)} requirements, {len(code_units)} code chunks across {len(valid_files)} files.")
    print(f"Loaded {len(gold_links)} gold links for evaluation.")

    # 1. Build BM25 Index
    print("\nBuilding BM25 index on code units...")
    bm25 = BM25Index()
    for cu in code_units:
        doc_text = f"{cu.file_path} {cu.code_key} {cu.content}"
        bm25.add_document(cu.code_unit_id, doc_text)
    bm25.build()

    # 2. Precompute Query Embeddings
    print("Precomputing requirement vectors...")
    req_index = {r.req_key: r for r in requirements}
    query_texts: dict[str, str] = {}
    query_vectors: dict[str, list[float]] = {}

    for req in requirements:
        raw_text = req.text
        rk = req.req_key
        exp_text = raw_text

        # Exception flow query expansion (for iTrust)
        if cfg["has_exceptions"] and "E" in rk:
            parent_match = re.match(r"(UC\d+)", rk)
            if parent_match:
                parent_key = parent_match.group(1)
                for suffix in ["S1", "S2", "S3", ""]:
                    parent = req_index.get(f"{parent_key}{suffix}")
                    if parent:
                        exp_text = f"{parent.text} Exception handling: {req.text}"
                        break

        query_texts[rk] = exp_text
        query_vectors[rk] = embed_text(
            exp_text,
            vector_size=settings.vector_size,
            model=settings.embedding_model,
            task_type="RETRIEVAL_QUERY",
        )

    configs = [
        {
            "name": "Full TraceAI (AST + BM25 + Dense + RRF + Cross-Encoder)",
            "use_bm25": True,
            "use_dense": True,
            "use_rrf": True,
            "use_reranker": True,
        },
        {
            "name": "w/o Cross-Encoder (AST + BM25 + Dense + RRF)",
            "use_bm25": True,
            "use_dense": True,
            "use_rrf": True,
            "use_reranker": False,
        },
        {
            "name": "w/o BM25 (AST + Dense + Cross-Encoder)",
            "use_bm25": False,
            "use_dense": True,
            "use_rrf": False,
            "use_reranker": True,
        },
        {
            "name": "Lexical BM25 Only (AST + BM25)",
            "use_bm25": True,
            "use_dense": False,
            "use_rrf": False,
            "use_reranker": False,
        },
        {
            "name": "Dense Semantic Only (AST + Dense BGE)",
            "use_bm25": False,
            "use_dense": True,
            "use_rrf": False,
            "use_reranker": False,
        },
    ]

    all_results = []
    retrieve_k = 100
    rrf_k = 60

    for c_idx, c_cfg in enumerate(configs, start=1):
        print(f"\n[{c_idx}/5] Evaluating: {c_cfg['name']}...")
        start_t = time.time()
        predicted: list[PredictedLink] = []

        for req in requirements:
            q_text = query_texts[req.req_key]
            q_vec = query_vectors[req.req_key]

            semantic_candidates = []
            if c_cfg["use_dense"]:
                semantic_candidates = vs.search_code_units(
                    project_id=project_id,
                    query_vector=q_vec,
                    limit=retrieve_k,
                )

            bm25_candidates = []
            if c_cfg["use_bm25"]:
                bm25_candidates = bm25.search(q_text, limit=retrieve_k)

            candidates = []
            if c_cfg["use_rrf"]:
                rrf_scores: dict[str, float] = {}
                for rank_i, c in enumerate(semantic_candidates, start=1):
                    rrf_scores[c["id"]] = rrf_scores.get(c["id"], 0) + 1.0 / (rrf_k + rank_i)
                for rank_i, c in enumerate(bm25_candidates, start=1):
                    rrf_scores[c["id"]] = rrf_scores.get(c["id"], 0) + 1.0 / (rrf_k + rank_i)

                all_ids = set(c["id"] for c in semantic_candidates) | set(c["id"] for c in bm25_candidates)
                semantic_map = {c["id"]: c for c in semantic_candidates}
                bm25_map = {c["id"]: c for c in bm25_candidates}

                for cid in all_ids:
                    base = semantic_map.get(cid, bm25_map.get(cid, {}))
                    semantic_entry = semantic_map.get(cid)
                    orig_score = float(semantic_entry["score"]) if semantic_entry else 0.0
                    candidates.append({
                        **base,
                        "id": cid,
                        "score": rrf_scores.get(cid, 0.0),
                        "embed_score": orig_score,
                    })
                candidates.sort(key=lambda x: x["score"], reverse=True)
            elif c_cfg["use_dense"] and not c_cfg["use_bm25"]:
                candidates = []
                for c in semantic_candidates:
                    candidates.append({**c, "embed_score": float(c["score"])})
            elif c_cfg["use_bm25"] and not c_cfg["use_dense"]:
                candidates = []
                for c in bm25_candidates:
                    candidates.append({**c, "embed_score": None})

            # Reranker stage
            if c_cfg["use_reranker"] and reranker_available() and candidates:
                rerank_pool = candidates[:80]
                enriched = []
                for c in rerank_pool:
                    cu = code_index.get(c["id"])
                    if cu is None:
                        continue
                    fname = Path(cu.file_path).name
                    rerank_text = f"File: {fname}\n{cu.content}"
                    enriched.append({
                        **c,
                        "code_key": cu.code_key,
                        "code_text": rerank_text[:2000],
                        "file_path": cu.file_path,
                    })
                reranked_chunks = rerank_candidates(q_text, enriched, top_k=len(enriched))
                best_per_file: dict[str, dict] = {}
                for c in reranked_chunks:
                    fp = c.get("file_path", "")
                    if not fp:
                        continue
                    if fp not in best_per_file or c["score"] > best_per_file[fp]["score"]:
                        best_per_file[fp] = c
                candidates = sorted(best_per_file.values(), key=lambda x: x["score"], reverse=True)
            else:
                seen_files: dict[str, dict] = {}
                for c in candidates:
                    cu = code_index.get(c["id"])
                    if cu is None:
                        continue
                    fp = cu.file_path
                    if fp not in seen_files or c["score"] > seen_files[fp]["score"]:
                        seen_files[fp] = c
                candidates = sorted(seen_files.values(), key=lambda x: x["score"], reverse=True)

            # Generate top-k file predictions matching persistence.py logic
            for rank_idx, candidate in enumerate(candidates[:k], start=1):
                cu = code_index.get(candidate["id"])
                if cu is None:
                    continue
                file_name = Path(cu.file_path).name
                score_val = candidate.get("embed_score")
                display_score = float(score_val) if score_val is not None else float(candidate["score"])
                display_score = min(display_score, 1.0)
                label = _score_to_label(display_score)
                predicted.append(PredictedLink(
                    req_key=req.req_key,
                    code_key=file_name,
                    score=display_score,
                    rank=rank_idx,
                    label=label,
                ))

        eval_res = evaluate(predicted, gold_links, k=k)
        elapsed = time.time() - start_t
        print(f"    -> Done in {elapsed:.2f}s | Hit@{k}: {eval_res.hit_at_k:.1f}% | MRR: {eval_res.mrr:.4f} | nDCG@{k}: {eval_res.ndcg_at_k:.4f} | Recall@{k}: {eval_res.recall_at_k:.4f}")

        all_results.append({
            "configuration": c_cfg["name"],
            "hit_at_10": round(eval_res.hit_at_k, 2),
            "mrr": round(eval_res.mrr, 4),
            "ndcg_at_10": round(eval_res.ndcg_at_k, 4),
            "recall_at_10": round(eval_res.recall_at_k, 4),
            "precision_at_10": round(eval_res.precision_at_k, 4),
            "map": round(eval_res.map_score, 4),
            "f1_at_10": round(eval_res.f1_at_k, 4),
            "elapsed_seconds": round(elapsed, 2),
        })

    # Save to JSON
    out_file = bdir / f"ablation_results_{ds_key}.json"
    with out_file.open("w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2)

    # Print Markdown & ASCII Table
    print("\n" + "=" * 90)
    print(f"TABLE V: COMPONENT ABLATION STUDY ({cfg['name']}, k={k})")
    print("=" * 90)
    header = f"{'Configuration':<52} | {'Hit@10':<8} | {'MRR':<8} | {'nDCG@10':<8} | {'Recall@10':<9} | {'MAP':<7}"
    print(header)
    print("-" * 90)
    for r in all_results:
        row = f"{r['configuration']:<52} | {r['hit_at_10']:>6.1f}% | {r['mrr']:>8.4f} | {r['ndcg_at_10']:>8.4f} | {r['recall_at_10']:>9.4f} | {r['map']:>7.4f}"
        print(row)
    print("=" * 90)
    print(f"\nAblation results successfully saved to: {out_file}")
    return all_results


def main():
    parser = argparse.ArgumentParser(description="Unified TraceAI Component Ablation Suite")
    parser.add_argument("--dataset", choices=["itrust", "libest", "etour", "all"], default="itrust",
                        help="Benchmark dataset to run ablation on (default: itrust)")
    parser.add_argument("--k", type=int, default=10, help="Top-k cutoff (default: 10)")
    args = parser.parse_args()

    datasets = ["itrust", "libest", "etour"] if args.dataset == "all" else [args.dataset]
    for ds in datasets:
        run_ablation_for_dataset(ds, k=args.k)


if __name__ == "__main__":
    main()
