#!/usr/bin/env python3
"""Download the official LibEST benchmark dataset from tobhey/finegrained-traceability.

Target directory: data/benchmarks/LibEST
Does NOT tamper with or touch iTrust or existing data.
"""
import json
import os
import sys
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LIBEST_DIR = PROJECT_ROOT / "data" / "benchmarks" / "LibEST"
REQ_DIR = LIBEST_DIR / "req"
CODE_DIR = LIBEST_DIR / "code"

REQ_DIR.mkdir(parents=True, exist_ok=True)
CODE_DIR.mkdir(parents=True, exist_ok=True)

GITHUB_API_BASE = "https://api.github.com/repos/tobhey/finegrained-traceability/contents/datasets/LibEST"
RAW_BASE = "https://raw.githubusercontent.com/tobhey/finegrained-traceability/main/datasets/LibEST"

def fetch_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "TraceAI-Benchmarker"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))

def download_file(url: str, dest: Path):
    req = urllib.request.Request(url, headers={"User-Agent": "TraceAI-Benchmarker"})
    with urllib.request.urlopen(req) as resp:
        content = resp.read()
    dest.write_bytes(content)

print(f"Target directory: {LIBEST_DIR}")

# 1. Download req_to_code_ground.txt
ground_url = f"{RAW_BASE}/req_to_code_ground.txt"
ground_dest = LIBEST_DIR / "req_to_code_ground.txt"
print(f"Downloading {ground_url} -> {ground_dest}...")
download_file(ground_url, ground_dest)

# 2. Download requirements
print("\nFetching requirements list...")
req_items = fetch_json(f"{GITHUB_API_BASE}/req")
print(f"Found {len(req_items)} requirement files. Downloading to {REQ_DIR}...")
for item in req_items:
    fname = item["name"]
    download_file(item["download_url"], REQ_DIR / fname)
print(f"Downloaded {len(req_items)} requirements.")

# 3. Download code files
print("\nFetching code files list...")
code_items = fetch_json(f"{GITHUB_API_BASE}/code")
print(f"Found {len(code_items)} code files. Downloading to {CODE_DIR}...")
for item in code_items:
    fname = item["name"]
    download_file(item["download_url"], CODE_DIR / fname)
print(f"Downloaded {len(code_items)} code files.")

print("\n" + "=" * 60)
print("LibEST benchmark dataset successfully downloaded!")
print(f"  Requirements: {len(list(REQ_DIR.glob('*.txt')))} files in {REQ_DIR}")
print(f"  Code:         {len(list(CODE_DIR.iterdir()))} files in {CODE_DIR}")
print(f"  Ground truth: {ground_dest}")
print("=" * 60)
