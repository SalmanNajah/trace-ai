#!/usr/bin/env python3
"""Unified TraceAI Benchmark Evaluation Suite.

Evaluates requirements-to-code traceability across all benchmark datasets:
  - iTrust (Java EHR System, CoEST/ICSME'21)
  - LibEST (C RFC 7030 Secure Transport, SEMERU/ICSE'20)
  - eTour (Java Tourism GIS System, TEFSE/CoEST)

Usage:
  python3 scripts/run_benchmark.py --dataset itrust --eval-only --k 10
  python3 scripts/run_benchmark.py --dataset libest --eval-only --k 10
  python3 scripts/run_benchmark.py --dataset etour --k 10
  python3 scripts/run_benchmark.py --dataset all --eval-only --k 10
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from traceai_v2.settings import load_settings
from traceai_v2.storage import (
    AnalysisRunRecord,
    CodeUnitRecord,
    ProjectRecord,
    RequirementRecord,
    TraceLinkRecord,
)
from traceai_v2.vector_store import VectorCollections, VectorStore
from traceai_v2.persistence import (
    persist_requirements_csv,
    persist_code_units_csv,
    generate_trace_links,
)
from traceai_v2.repo_ingestion import LocalRepoIngestionPipeline
from traceai_v2.evaluation import (
    GoldLink,
    PredictedLink,
    evaluate,
    format_results_table,
    save_results_json,
)

DATASET_CONFIGS = {
    "itrust": {
        "name": "iTrust (Java EHR System)",
        "project_id": "itrust-benchmark",
        "dir": PROJECT_ROOT / "data" / "benchmarks" / "iTrust",
        "req_csv": "requirements_itrust.csv",
        "gold_csv": "gold_links_itrust.csv",
        "solution_file": "itrust_solution_links.txt",
        "code_dir": "code",
        "language": "java",
        "notes": "iTrust benchmark, k=10, dataset=CoEST/ICSME'21, matching=file-level",
    },
    "libest": {
        "name": "LibEST (C RFC 7030 Secure Transport)",
        "project_id": "libest-benchmark",
        "dir": PROJECT_ROOT / "data" / "benchmarks" / "LibEST",
        "req_csv": "requirements_libest.csv",
        "gold_csv": "gold_links_libest.csv",
        "solution_file": "req_to_code_ground.txt",
        "code_dir": "code",
        "language": "c",
        "notes": "LibEST C benchmark, k=10, dataset=SEMERU/ICSE'20, matching=file-level",
    },
    "etour": {
        "name": "eTour (Java Tourism GIS System)",
        "project_id": "etour-benchmark",
        "dir": PROJECT_ROOT / "data" / "benchmarks" / "eTour",
        "req_csv": "requirements_etour.csv",
        "gold_csv": "gold_links_etour.csv",
        "solution_file": "etour_solution_links_english.txt",
        "code_dir": "code",
        "language": "java",
        "notes": "eTour benchmark, k=10, dataset=TEFSE/CoEST, matching=file-level",
    },
}


def build_requirements_csv(ds_key: str) -> Path:
    cfg = DATASET_CONFIGS[ds_key]
    bdir = cfg["dir"]
    req_dir = bdir / "req"
    output = bdir / cfg["req_csv"]
    now = datetime.now(timezone.utc).isoformat()

    rows = []
    for req_file in sorted(req_dir.glob("*.txt")):
        key = req_file.stem  # e.g., "UC10E1", "RQ1", "UC1"
        text = req_file.read_text(encoding="utf-8", errors="ignore").strip()
        text = " ".join(text.split())
        rows.append({
            "project_id": cfg["project_id"],
            "requirement_id": str(uuid.uuid4()),
            "req_key": key,
            "text": text,
            "source_doc": req_file.name,
            "version": 1,
            "created_at": now,
        })

    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "project_id", "requirement_id", "req_key", "text",
            "source_doc", "version", "created_at",
        ])
        writer.writeheader()
        writer.writerows(rows)

    print(f"  [1/4] Built {len(rows)} requirements -> {output}")
    return output


def build_gold_links_csv(ds_key: str) -> Path:
    cfg = DATASET_CONFIGS[ds_key]
    bdir = cfg["dir"]
    sol_file = bdir / cfg["solution_file"]
    output = bdir / cfg["gold_csv"]

    links = []
    with sol_file.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or ":" not in line:
                continue
            req_part, code_part = line.split(":", 1)
            req_key = req_part.replace(".txt", "").strip()
            code_files = code_part.strip().split()
            for code_id in code_files:
                code_id = code_id.strip()
                if code_id:
                    links.append({
                        "req_key": req_key,
                        "code_identifier": code_id,
                        "relevance": "1.0",
                    })

    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["req_key", "code_identifier", "relevance"])
        writer.writeheader()
        writer.writerows(links)

    print(f"  [2/4] Built {len(links)} gold links -> {output}")
    return output


def run_benchmark_for_dataset(ds_key: str, k: int = 10, eval_only: bool = False) -> None:
    cfg = DATASET_CONFIGS[ds_key]
    project_id = cfg["project_id"]
    bdir = cfg["dir"]

    print("\n" + "=" * 70)
    print(f"  TraceAI Benchmark: {cfg['name']}")
    print(f"  Project ID: {project_id} | Language: {cfg['language']}")
    print("=" * 70)

    settings = load_settings()
    engine = create_engine(settings.database_url)
    vs = VectorStore(
        url=settings.qdrant_url,
        collections=VectorCollections(
            requirements=settings.qdrant_requirements_collection,
            code_units=settings.qdrant_code_units_collection,
            size=settings.vector_size,
        ),
    )

    req_csv = build_requirements_csv(ds_key)
    gold_csv = build_gold_links_csv(ds_key)

    if not eval_only:
        with Session(engine) as session:
            proj = session.scalars(select(ProjectRecord).where(ProjectRecord.project_id == project_id)).first()
            if not proj:
                proj = ProjectRecord(
                    project_id=project_id,
                    name=cfg["name"],
                    description=f"Automated benchmark project for {cfg['name']}",
                    created_at=datetime.now(timezone.utc),
                )
                session.add(proj)
                session.commit()

            print("\n  [3/4] Indexing requirements (BGE dense vectors)...")
            req_res = persist_requirements_csv(
                session=session,
                vector_store=vs,
                csv_path=str(req_csv),
                vector_size=settings.vector_size,
                embedding_model=settings.embedding_model,
            )
            print(f"    Indexed {req_res.inserted_requirements} requirements.")

            print(f"\n  [4/4] Parsing and indexing {cfg['language'].upper()} code repository...")
            pipeline = LocalRepoIngestionPipeline(data_root=PROJECT_ROOT / "data")
            ingest_res = pipeline.ingest(project_id, bdir / cfg["code_dir"])
            processed_csv = ingest_res["processed_csv"]
            print(f"    Extracted {ingest_res['code_units_written']} code units.")

            cu_res = persist_code_units_csv(
                session=session,
                vector_store=vs,
                csv_path=processed_csv,
                vector_size=settings.vector_size,
                embedding_model=settings.embedding_model,
            )
            print(f"    Persisted & embedded {cu_res.inserted_code_units} units in Qdrant & DB.")

            print(f"\n  Generating Trace Links (Hybrid Retrieval + Cross-Encoder, top_k={k})...")
            run_record = AnalysisRunRecord(
                project_id=project_id,
                commit_sha=None,
                changed_files="[]",
                requirements_count=req_res.inserted_requirements,
                code_units_count=cu_res.inserted_code_units,
                trace_links_count=0,
                execution_time_seconds=0.0,
                created_at=datetime.now(timezone.utc),
            )
            session.add(run_record)
            session.flush()
            run_id = run_record.id

            trace_res = generate_trace_links(
                session=session,
                vector_store=vs,
                project_id=project_id,
                run_id=run_id,
                vector_size=settings.vector_size,
                top_k=k,
                embedding_model=settings.embedding_model,
            )
            print(f"    Generated {trace_res.links_generated} predicted trace links.")

    # Evaluation step (identical for all datasets)
    with Session(engine) as session:
        code_units = session.scalars(select(CodeUnitRecord).where(CodeUnitRecord.project_id == project_id)).all()
        code_key_to_file = {cu.code_key: Path(cu.file_path).name for cu in code_units}
        valid_files = set(code_key_to_file.values())

        gold_links = []
        with gold_csv.open("r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                cfile = row["code_identifier"].strip()
                if cfile in valid_files:
                    gold_links.append(GoldLink(
                        req_key=row["req_key"],
                        code_key=cfile,
                        relevance=float(row.get("relevance", "1.0")),
                    ))

        links = session.scalars(
            select(TraceLinkRecord)
            .where(TraceLinkRecord.project_id == project_id)
            .order_by(TraceLinkRecord.req_key, TraceLinkRecord.rank)
        ).all()

        predicted = []
        seen = set()
        for l in links:
            fname = code_key_to_file.get(l.code_key, l.code_key)
            pair_key = (l.req_key, fname)
            if pair_key not in seen:
                seen.add(pair_key)
                predicted.append(PredictedLink(
                    req_key=l.req_key,
                    code_key=fname,
                    score=l.score,
                    rank=len([p for p in predicted if p.req_key == l.req_key]) + 1,
                    label=l.label,
                ))

        eval_res = evaluate(predicted, gold_links, k=k)
        eval_res.notes = cfg["notes"]

        print("\n" + "=" * 60)
        print(format_results_table(eval_res))
        print("=" * 60)

        out_json = bdir / f"eval_results_{ds_key}.json"
        save_results_json(eval_res, out_json)
        print(f"\nEvaluation JSON successfully saved to: {out_json}")


def main():
    parser = argparse.ArgumentParser(description="Unified TraceAI Benchmark Evaluation Suite")
    parser.add_argument("--dataset", choices=["itrust", "libest", "etour", "all"], default="itrust",
                        help="Benchmark dataset to evaluate (default: itrust)")
    parser.add_argument("--eval-only", action="store_true", help="Evaluate existing database links only")
    parser.add_argument("--k", type=int, default=10, help="Top-k cutoff (default: 10)")
    args = parser.parse_args()

    datasets = ["itrust", "libest", "etour"] if args.dataset == "all" else [args.dataset]
    for ds in datasets:
        run_benchmark_for_dataset(ds, k=args.k, eval_only=args.eval_only)


if __name__ == "__main__":
    main()
