from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv
import uvicorn

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

# Load .env from project root (contains GEMINI_API_KEY, DB URL, etc.)
load_dotenv(REPO_ROOT / ".env")


if __name__ == "__main__":
    uvicorn.run("traceai_v2.api:app", host="0.0.0.0", port=8100, reload=True)
