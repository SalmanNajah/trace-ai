#!/usr/bin/env python3
"""iTrust Benchmark — IEEE-compliant traceability evaluation.

Usage:
    python3 scripts/run_benchmark.py --k 10
    python3 scripts/run_benchmark.py --eval-only --k 10
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

BENCHMARK_DIR = Path(__file__).resolve().parent.parent / "data" / "benchmarks" / "iTrust"
PROJECT_ID = "itrust-benchmark"
API_BASE = os.environ.get("TRACEAI_API_BASE_URL", "http://127.0.0.1:8100")


# ---------------------------------------------------------------------------
# Step 1a: Build requirements CSV directly (bypass splitting pipeline)
# ---------------------------------------------------------------------------

def build_requirements_csv() -> Path:
    """Build a processed CSV with original UC keys — no splitting, no renaming."""
    req_dir = BENCHMARK_DIR / "req"
    output = BENCHMARK_DIR / "requirements_itrust.csv"
    now = datetime.now(timezone.utc).isoformat()

    rows = []
    for req_file in sorted(req_dir.glob("*.txt")):
        uc_key = req_file.stem  # e.g. "UC10E1"
        text = req_file.read_text(encoding="utf-8", errors="ignore").strip()
        text = " ".join(text.split())  # collapse whitespace
        rows.append({
            "project_id": PROJECT_ID,
            "requirement_id": str(uuid.uuid4()),
            "req_key": uc_key,
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

    print(f"  Built {len(rows)} requirements (UC keys) → {output}")
    return output


# ---------------------------------------------------------------------------
# Step 1b: Build gold links CSV with UC keys
# ---------------------------------------------------------------------------

def build_gold_links_csv() -> Path:
    """Convert iTrust solution links to gold CSV using UC keys directly."""
    solution_file = BENCHMARK_DIR / "itrust_solution_links.txt"
    output = BENCHMARK_DIR / "gold_links_itrust.csv"

    links = []
    with solution_file.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or ":" not in line:
                continue
            req_filename, code_filename = line.split(":", 1)
            req_filename = req_filename.strip()
            code_filename = code_filename.strip()

            uc_key = Path(req_filename).stem  # "UC10E1.txt" → "UC10E1"
            links.append({
                "req_key": uc_key,
                "code_identifier": code_filename,
                "relevance": "1.0",
            })

    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["req_key", "code_identifier", "relevance"])
        writer.writeheader()
        writer.writerows(links)

    print(f"  Built {len(links)} gold links → {output}")
    return output


# ---------------------------------------------------------------------------
# Steps 2-5: Ingest via API
# ---------------------------------------------------------------------------

def ingest_via_api(requirements_csv: Path):
    """Upload requirements CSV directly, ingest code, generate trace links."""

    def curl_post(url, data=None, files=None):
        cmd = ["curl", "-s", "-w", "\n%{http_code}", "-X", "POST"]
        if files:
            cmd += ["-F", files]
        elif data:
            cmd += ["-H", "Content-Type: application/json", "-d", json.dumps(data)]
        cmd.append(url)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        lines = result.stdout.strip().rsplit("\n", 1)
        body = lines[0] if len(lines) > 1 else ""
        code = int(lines[-1]) if lines[-1].isdigit() else 0
        return code, body

    # Step 2: Reset
    print("\n--- Step 2: Reset project ---")
    code, body = curl_post(f"{API_BASE}/api/projects/{PROJECT_ID}/reset")
    print(f"  Reset: {code}")

    # Step 3: Upload requirements CSV directly (bypass pipeline)
    print("\n--- Step 3: Upload requirements ---")
    # We bypass the requirements pipeline and use persistence directly
    # by calling the CSV upload endpoint
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from traceai_v2.settings import load_settings
    from traceai_v2.persistence import persist_requirements_csv
    from traceai_v2.vector_store import VectorStore, VectorCollections

    settings = load_settings()
    engine = create_engine(settings.database_url)
    vs = VectorStore(url=settings.qdrant_url,
                     collections=VectorCollections(
                         requirements=settings.qdrant_requirements_collection,
                         code_units=settings.qdrant_code_units_collection,
                         size=settings.vector_size,
                     ))

    with Session(engine) as session:
        result = persist_requirements_csv(
            session=session,
            vector_store=vs,
            csv_path=str(requirements_csv),
            vector_size=settings.vector_size,
            embedding_model=settings.embedding_model,
        )
    print(f"  Uploaded: {result.inserted_requirements} requirements (UC keys preserved)")

    # Step 4: Ingest code via API
    print("\n--- Step 4: Ingest code repository ---")
    code_dir = str(BENCHMARK_DIR / "code")
    code, body = curl_post(
        f"{API_BASE}/api/projects/{PROJECT_ID}/repo/ingest",
        data={"repo_path": code_dir}
    )
    if code == 200:
        data = json.loads(body)
        print(f"  Indexed: {data['persisted']['inserted_code_units']} code units")
    else:
        print(f"  Error: {code} — {body[:200]}")
        sys.exit(1)

    # Step 5: Generate trace links via API
    print("\n--- Step 5: Generate trace links ---")
    code, body = curl_post(
        f"{API_BASE}/api/projects/{PROJECT_ID}/trace-links/generate",
        data={"top_k": 10}
    )
    if code == 200:
        data = json.loads(body)
        print(f"  Generated: {data['generated']['links_generated']} links")
        print(f"  Coverage: {data['matrix_summary']['coverage_percentage']}%")
    else:
        print(f"  Error: {code} — {body[:200]}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Step 6: Evaluate (file-level gold matching)
# ---------------------------------------------------------------------------

def run_evaluation(gold_csv: Path, k: int):
    """Evaluate predicted links against gold standard with file-level matching."""
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    from traceai_v2.settings import load_settings
    from traceai_v2.storage import TraceLinkRecord, CodeUnitRecord
    from traceai_v2.evaluation import (
        GoldLink, PredictedLink,
        evaluate, format_results_table, save_results_json,
    )

    settings = load_settings()
    engine = create_engine(settings.database_url)

    with Session(engine) as session:
        code_units = session.scalars(
            select(CodeUnitRecord).where(CodeUnitRecord.project_id == PROJECT_ID)
        ).all()

        # Map code_key → filename for file-level matching
        code_key_to_file: dict[str, str] = {}
        for cu in code_units:
            code_key_to_file[cu.code_key] = Path(cu.file_path).name

        # Build gold links at FILE level (one gold per req+file pair)
        # This is the correct granularity for iTrust
        gold_links = []
        unresolved = 0
        indexed_files = set(code_key_to_file.values())
        with gold_csv.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                code_file = row["code_identifier"].strip()
                if code_file in indexed_files:
                    gold_links.append(GoldLink(
                        req_key=row["req_key"],
                        code_key=code_file,  # Use filename as the key
                        relevance=float(row.get("relevance", "1.0")),
                    ))
                else:
                    unresolved += 1

        print(f"\n  Gold links: {len(gold_links)} (file-level)")
        if unresolved:
            print(f"  Gold links unresolved: {unresolved}")

        # Build predicted links, mapped to file level
        links = session.scalars(
            select(TraceLinkRecord)
            .where(TraceLinkRecord.project_id == PROJECT_ID)
            .order_by(TraceLinkRecord.req_key, TraceLinkRecord.rank)
        ).all()

        # Deduplicate predicted links per req_key at file level
        # (multiple methods from same file → one file-level prediction)
        predicted = []
        seen: set[tuple[str, str]] = set()
        for l in links:
            file_name = code_key_to_file.get(l.code_key, l.code_key)
            key = (l.req_key, file_name)
            if key not in seen:
                seen.add(key)
                predicted.append(PredictedLink(
                    req_key=l.req_key,
                    code_key=file_name,  # Match at file level
                    score=float(l.score),
                    rank=len([p for p in predicted if p.req_key == l.req_key]) + 1,
                    label=l.label,
                ))

    print(f"  Predicted links: {len(predicted)} (deduplicated to file-level)")

    result = evaluate(predicted, gold_links, k=k)
    result.embedding_provider = os.environ.get("TRACEAI_EMBEDDING_PROVIDER", "unknown")
    provider = result.embedding_provider
    if provider == "local":
        result.embedding_model = os.environ.get("TRACEAI_LOCAL_MODEL", "BAAI/bge-base-en-v1.5")
    elif provider in ("huggingface", "hf"):
        result.embedding_model = "BAAI/bge-base-en-v1.5"
    else:
        result.embedding_model = os.environ.get("TRACEAI_EMBEDDING_MODEL", "unknown")
    result.parser_type = "tree-sitter"
    result.notes = f"iTrust benchmark, k={k}, dataset=CoEST/ICSME'21, matching=file-level"

    print()
    print(format_results_table(result))

    output_json = BENCHMARK_DIR / "eval_results_itrust.json"
    save_results_json(result, output_json)
    print(f"\nJSON results saved to: {output_json}")


def regenerate_and_eval(k: int):
    """Regenerate trace links only (skip reset/ingestion), then evaluate."""
    def curl_post(url, data=None):
        cmd = ["curl", "-s", "-w", "\n%{http_code}", "-X", "POST",
               "-H", "Content-Type: application/json", "-d", json.dumps(data)]
        cmd.append(url)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        lines = result.stdout.strip().rsplit("\n", 1)
        body = lines[0] if len(lines) > 1 else ""
        code = int(lines[-1]) if lines[-1].isdigit() else 0
        return code, body

    print("\n--- Regenerate trace links (reusing existing embeddings) ---")
    code, body = curl_post(
        f"{API_BASE}/api/projects/{PROJECT_ID}/trace-links/generate",
        data={"top_k": 10}
    )
    if code == 200:
        data = json.loads(body)
        print(f"  Generated: {data['generated']['links_generated']} links")
        print(f"  Coverage: {data['matrix_summary']['coverage_percentage']}%")
    else:
        print(f"  Error: {code} — {body[:200]}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Run iTrust benchmark evaluation.")
    parser.add_argument("--eval-only", action="store_true", help="Skip ingestion, evaluate only")
    parser.add_argument("--reeval", action="store_true",
                        help="Regenerate trace links + evaluate (skip reset/re-embedding)")
    parser.add_argument("--k", type=int, default=10, help="Top-k cutoff (default: 10)")
    args = parser.parse_args()

    print("=" * 60)
    print("  iTrust Benchmark Evaluation")
    print("  Dataset: 131 requirements, 19+ code files, 285 gold links")
    print("  Source: CoEST / ICSME'21 (peer-reviewed)")
    print("=" * 60)

    if not BENCHMARK_DIR.exists():
        print(f"\nError: Benchmark data not found at {BENCHMARK_DIR}")
        sys.exit(1)

    print("\n--- Step 1: Convert iTrust data ---")
    req_csv = build_requirements_csv()
    gold_csv = build_gold_links_csv()

    if args.reeval:
        regenerate_and_eval(k=args.k)
    elif not args.eval_only:
        ingest_via_api(req_csv)

    print("\n--- Step 6: Evaluate ---")
    run_evaluation(gold_csv, k=args.k)


if __name__ == "__main__":
    main()

