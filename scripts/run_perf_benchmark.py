#!/usr/bin/env python3
"""Performance & Scalability Benchmark — timing stages at different scales.

Usage:
    python3 scripts/run_perf_benchmark.py
"""
from __future__ import annotations

import csv
import json
import os
import shutil
import sys
import tempfile
import time
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

BENCHMARK_DIR = Path(__file__).resolve().parent.parent / "data" / "benchmarks" / "iTrust"
PROJECT_ID = "itrust-perf-benchmark"
API_BASE = os.environ.get("TRACEAI_API_BASE_URL", "http://127.0.0.1:8100")


def curl_post(url: str, data: dict | None = None) -> tuple[int, str]:
    cmd = ["curl", "-s", "-w", "\n%{http_code}", "-X", "POST"]
    if data:
        cmd += ["-H", "Content-Type: application/json", "-d", json.dumps(data)]
    cmd.append(url)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        lines = result.stdout.strip().rsplit("\n", 1)
        body = lines[0] if len(lines) > 1 else ""
        code = int(lines[-1]) if lines[-1].isdigit() else 0
        return code, body
    except subprocess.TimeoutExpired:
        return 504, "Timeout"


def run_scale_experiment(
    *,
    scale_name: str,
    req_count: int,
    code_count: int,
    all_req_rows: list[dict],
    all_code_files: list[Path],
) -> dict:
    print(f"\n>>> Running scale: {scale_name.upper()} ({req_count} reqs, {code_count} code files)")

    # 1. Create temp directory
    with tempfile.TemporaryDirectory() as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        temp_code_dir = temp_dir / "code"
        temp_code_dir.mkdir()

        # 2. Slice requirements and save CSV
        import copy
        req_slice = [copy.deepcopy(row) for row in all_req_rows[:req_count]]
        for row in req_slice:
            row["project_id"] = PROJECT_ID
        temp_req_csv = temp_dir / "requirements.csv"
        with temp_req_csv.open("w", newline="", encoding="utf-8") as f:
            if req_slice:
                writer = csv.DictWriter(f, fieldnames=req_slice[0].keys())
                writer.writeheader()
                writer.writerows(req_slice)

        # 3. Slice and copy code files
        code_slice = all_code_files[:code_count]
        for fpath in code_slice:
            # Recreate relative path structure in the temp directory to maintain context
            rel_path = fpath.relative_to(BENCHMARK_DIR / "code")
            dest = temp_code_dir / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(fpath, dest)

        # 4. Reset project database/vector collections
        print("  Resetting project...")
        code, body = curl_post(f"{API_BASE}/api/projects/{PROJECT_ID}/reset")
        if code != 200:
            print(f"  Reset failed: {code} — {body}")
            sys.exit(1)

        # Recreate the project so it exists in database
        print("  Re-creating project...")
        code, body = curl_post(
            f"{API_BASE}/api/projects",
            data={"name": PROJECT_ID, "description": "Benchmark project for performance evaluation"}
        )
        if code not in (200, 201, 409):
            print(f"  Project creation failed: {code} — {body}")
            sys.exit(1)

        # 5. Ingest requirements (Measure Embed Reqs Time)
        print("  Ingesting requirements...")
        from sqlalchemy import create_engine
        from sqlalchemy.orm import Session
        from traceai_v2.settings import load_settings
        from traceai_v2.persistence import persist_requirements_csv
        from traceai_v2.vector_store import VectorStore, VectorCollections

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

        start_req = time.time()
        with Session(engine) as session:
            persist_requirements_csv(
                session=session,
                vector_store=vs,
                csv_path=str(temp_req_csv),
                vector_size=settings.vector_size,
                embedding_model=settings.embedding_model,
            )
        embed_req_sec = time.time() - start_req
        print(f"    Completed in {embed_req_sec:.2f}s")

        # 6. Ingest code (Measure Embed Code Time)
        print("  Ingesting repository...")
        start_code = time.time()
        code, body = curl_post(
            f"{API_BASE}/api/projects/{PROJECT_ID}/repo/ingest",
            data={"repo_path": str(temp_code_dir)},
        )
        if code != 200:
            print(f"  Code ingestion failed: {code} — {body}")
            sys.exit(1)
        embed_code_sec = time.time() - start_code
        print(f"    Completed in {embed_code_sec:.2f}s")

        # 7. Generate trace links (Measure Trace Generation Time)
        print("  Generating trace links...")
        start_trace = time.time()
        code, body = curl_post(
            f"{API_BASE}/api/projects/{PROJECT_ID}/trace-links/generate",
            data={"top_k": 10},
        )
        if code != 200:
            print(f"  Trace link generation failed: {code} — {body}")
            sys.exit(1)
        trace_gen_sec = time.time() - start_trace
        print(f"    Completed in {trace_gen_sec:.2f}s")

        total_sec = embed_req_sec + embed_code_sec + trace_gen_sec
        return {
            "scale": scale_name,
            "requirements": req_count,
            "code_chunks": len(code_slice),
            "embed_req_sec": round(embed_req_sec, 2),
            "embed_code_sec": round(embed_code_sec, 2),
            "trace_gen_sec": round(trace_gen_sec, 2),
            "total_sec": round(total_sec, 2),
        }


def main():
    print("=" * 60)
    print("  TraceAI Performance & Scalability Benchmark")
    print("=" * 60)

    if not BENCHMARK_DIR.exists():
        print(f"Error: Benchmark dir not found at {BENCHMARK_DIR}")
        sys.exit(1)

    req_csv = BENCHMARK_DIR / "requirements_itrust.csv"
    if not req_csv.exists():
        print(f"Error: Requirements file not found at {req_csv}. Run run_benchmark.py first.")
        sys.exit(1)

    # Load all requirements
    with req_csv.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        all_req_rows = list(reader)

    # Load all Java files
    code_dir = BENCHMARK_DIR / "code"
    all_code_files = sorted(list(code_dir.glob("**/*.java")))

    print(f"Loaded {len(all_req_rows)} requirements and {len(all_code_files)} code files.")

    # Configure experiments
    scales = [
        {"name": "small", "reqs": 25, "code": 50},
        {"name": "medium", "reqs": 50, "code": 100},
        {"name": "full", "reqs": len(all_req_rows), "code": len(all_code_files)},
    ]

    results = []
    for scale in scales:
        res = run_scale_experiment(
            scale_name=str(scale["name"]),
            req_count=int(scale["reqs"]),
            code_count=int(scale["code"]),
            all_req_rows=all_req_rows,
            all_code_files=all_code_files,
        )
        results.append(res)

    # Output CSV results
    out_csv = BENCHMARK_DIR / "perf_results.csv"
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "scale", "requirements", "code_chunks",
            "embed_req_sec", "embed_code_sec", "trace_gen_sec", "total_sec"
        ])
        writer.writeheader()
        writer.writerows(results)

    print(f"\nScalability benchmark finished! Results saved to: {out_csv}")
    print("=" * 60)


if __name__ == "__main__":
    main()
