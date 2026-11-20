#!/usr/bin/env python3
"""Download and prepare the official eTour benchmark dataset from Hey & Frattini RE'26.

Target directory: data/benchmarks/eTour
Dataset: 58 use-case requirements, 117 Java code files, 308 gold trace links.
"""
import csv
import json
import urllib.request
from pathlib import Path

BASE_URL = "https://raw.githubusercontent.com/tobhey/finegrained-traceability/main/datasets/eTour"
API_URL = "https://api.github.com/repos/tobhey/finegrained-traceability/contents/datasets/eTour"

DATASET_DIR = Path(__file__).resolve().parent.parent / "data" / "benchmarks" / "eTour"
CODE_DIR = DATASET_DIR / "code"
REQ_DIR = DATASET_DIR / "req"


def download_file(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "TraceAI-Bench"})
    with urllib.request.urlopen(req) as resp, dest.open("wb") as f:
        f.write(resp.read())


def main() -> None:
    DATASET_DIR.mkdir(parents=True, exist_ok=True)
    CODE_DIR.mkdir(parents=True, exist_ok=True)
    REQ_DIR.mkdir(parents=True, exist_ok=True)

    print("Fetching file manifests for eTour from GitHub...")
    # 1. Download solution links and manifests
    download_file(f"{BASE_URL}/etour_solution_links_english.txt", DATASET_DIR / "etour_solution_links_english.txt")
    download_file(f"{BASE_URL}/all_code_filenames.txt", DATASET_DIR / "all_code_filenames.txt")
    download_file(f"{BASE_URL}/all_req_filenames.txt", DATASET_DIR / "all_req_filenames.txt")

    # 2. Fetch code file list from GitHub API
    code_req = urllib.request.Request(f"{API_URL}/code", headers={"User-Agent": "TraceAI-Bench"})
    with urllib.request.urlopen(code_req) as resp:
        code_items = json.loads(resp.read().decode("utf-8"))

    print(f"Downloading {len(code_items)} Java code files...")
    for item in code_items:
        dest = CODE_DIR / item["name"]
        if not dest.exists():
            download_file(item["download_url"], dest)

    # 3. Fetch req file list from GitHub API
    req_api_req = urllib.request.Request(f"{API_URL}/req", headers={"User-Agent": "TraceAI-Bench"})
    with urllib.request.urlopen(req_api_req) as resp:
        req_items = json.loads(resp.read().decode("utf-8"))

    print(f"Downloading {len(req_items)} requirement files...")
    for item in req_items:
        dest = REQ_DIR / item["name"]
        if not dest.exists():
            download_file(item["download_url"], dest)

    print(f"Downloaded eTour successfully to {DATASET_DIR}")


if __name__ == "__main__":
    main()
