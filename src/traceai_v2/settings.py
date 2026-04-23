from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_root: Path
    database_url: str
    qdrant_url: str
    qdrant_requirements_collection: str
    qdrant_code_units_collection: str
    vector_size: int
    gemini_api_key: str
    embedding_model: str


def load_settings() -> Settings:
    repo_root = Path(__file__).resolve().parents[2]
    data_root = Path(os.getenv("TRACEAI_DATA_ROOT", str(repo_root / "data"))).resolve()
    return Settings(
        data_root=data_root,
        database_url=os.getenv(
            "TRACEAI_DATABASE_URL",
            "postgresql+psycopg://traceai:traceai@localhost:5434/traceai",
        ),
        qdrant_url=os.getenv("TRACEAI_QDRANT_URL", "http://localhost:6333"),
        qdrant_requirements_collection=os.getenv("TRACEAI_QDRANT_REQUIREMENTS_COLLECTION", "requirements_v2"),
        qdrant_code_units_collection=os.getenv("TRACEAI_QDRANT_CODE_COLLECTION", "code_units_v2"),
        vector_size=int(os.getenv("TRACEAI_VECTOR_SIZE", "768")),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        embedding_model=os.getenv("TRACEAI_EMBEDDING_MODEL", "gemini-embedding-001"),
    )
