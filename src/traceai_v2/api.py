from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import select

from .persistence import (
    build_trace_matrix,
    generate_trace_links,
    persist_code_units_csv,
    persist_requirements_csv,
    reset_project,
)
from .repo_ingestion import LocalRepoIngestionPipeline, RepoIngestionError
from .requirements_ingestion import IngestionError, RequirementsIngestionPipeline
from .settings import load_settings
from .storage import CodeUnitRecord, RequirementRecord, build_database, init_db
from .vector_store import VectorCollections, VectorStore


settings = load_settings()
database = build_database(settings.database_url)
vector_store = VectorStore(
    url=settings.qdrant_url,
    collections=VectorCollections(
        requirements=settings.qdrant_requirements_collection,
        code_units=settings.qdrant_code_units_collection,
        size=settings.vector_size,
    ),
)
requirements_pipeline = RequirementsIngestionPipeline(settings.data_root)
repo_pipeline = LocalRepoIngestionPipeline(settings.data_root)

app = FastAPI(title="TraceAI V2 API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)
startup_error: Optional[str] = None


@app.on_event("startup")
def on_startup() -> None:
    global startup_error
    try:
        init_db(database)
        vector_store.ensure_collections()
        startup_error = None
    except Exception as exc:
        startup_error = str(exc)


@app.get("/health")
def health() -> dict[str, str]:
    if startup_error:
        return {"status": "degraded", "detail": startup_error}
    return {"status": "ok"}


def ensure_ready() -> None:
    if startup_error:
        raise HTTPException(status_code=503, detail=f"Startup dependency error: {startup_error}")


@app.post("/api/projects/{project_id}/requirements/upload")
async def upload_requirements(
    project_id: str,
    file: UploadFile = File(...),
    source_doc: Optional[str] = Form(default=None),
    version: Optional[int] = Form(default=None),
) -> dict[str, object]:
    ensure_ready()
    suffix = Path(file.filename or "upload.txt").suffix
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name
        ingest_result = requirements_pipeline.ingest(
            project_id=project_id,
            input_file=tmp_path,
            source_doc=source_doc or file.filename,
            version=version,
        )
    except IngestionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with database.SessionLocal() as session:
        persist_result = persist_requirements_csv(
            session=session,
            vector_store=vector_store,
            csv_path=str(ingest_result["processed_csv"]),
            vector_size=settings.vector_size,
            embedding_model=settings.embedding_model,
        )
        vector_counts = vector_store.count_points(project_id)
    return {
        "ingest": ingest_result,
        "persisted": {
            "inserted_requirements": persist_result.inserted_requirements,
            "requirement_vectors": persist_result.requirement_vectors,
        },
        "vector_counts": vector_counts,
    }


class RepoIngestRequest(BaseModel):
    repo_path: str
    version: Optional[int] = None
    commit_sha: Optional[str] = None


@app.post("/api/projects/{project_id}/repo/ingest")
def ingest_repo(project_id: str, body: RepoIngestRequest) -> dict[str, object]:
    ensure_ready()
    try:
        ingest_result = repo_pipeline.ingest(
            project_id=project_id,
            repo_path=body.repo_path,
            version=body.version,
            commit_sha=body.commit_sha,
        )
    except RepoIngestionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with database.SessionLocal() as session:
        persist_result = persist_code_units_csv(
            session=session,
            vector_store=vector_store,
            csv_path=str(ingest_result["processed_csv"]),
            vector_size=settings.vector_size,
            embedding_model=settings.embedding_model,
        )
        vector_counts = vector_store.count_points(project_id)
    return {
        "ingest": ingest_result,
        "persisted": {
            "inserted_code_units": persist_result.inserted_code_units,
            "code_vectors": persist_result.code_vectors,
        },
        "vector_counts": vector_counts,
    }


@app.get("/api/projects/{project_id}/requirements")
def list_requirements(project_id: str) -> list[dict[str, object]]:
    ensure_ready()
    with database.SessionLocal() as session:
        records = session.scalars(
            select(RequirementRecord).where(RequirementRecord.project_id == project_id).order_by(RequirementRecord.id)
        ).all()
    return [
        {
            "requirement_id": item.requirement_id,
            "req_key": item.req_key,
            "text": item.text,
            "source_doc": item.source_doc,
            "version": item.version,
            "created_at": item.created_at.isoformat(),
        }
        for item in records
    ]


@app.get("/api/projects/{project_id}/code-units")
def list_code_units(project_id: str, limit: int = 200) -> list[dict[str, object]]:
    ensure_ready()
    with database.SessionLocal() as session:
        records = session.scalars(
            select(CodeUnitRecord).where(CodeUnitRecord.project_id == project_id).order_by(CodeUnitRecord.id.desc()).limit(limit)
        ).all()
    return [
        {
            "code_unit_id": item.code_unit_id,
            "code_key": item.code_key,
            "file_path": item.file_path,
            "symbol": item.symbol,
            "start_line": item.start_line,
            "end_line": item.end_line,
            "language": item.language,
            "chunk_type": item.chunk_type,
            "content": item.content,
        }
        for item in records
    ]


@app.get("/api/projects/{project_id}/vector-stats")
def vector_stats(project_id: str) -> dict[str, int]:
    ensure_ready()
    return vector_store.count_points(project_id)


class TraceGenerateRequest(BaseModel):
    top_k: int = 5


@app.post("/api/projects/{project_id}/trace-links/generate")
def generate_project_trace_links(project_id: str, body: TraceGenerateRequest) -> dict[str, object]:
    ensure_ready()
    if body.top_k < 1 or body.top_k > 20:
        raise HTTPException(status_code=400, detail="top_k must be between 1 and 20")

    with database.SessionLocal() as session:
        result = generate_trace_links(
            session=session,
            vector_store=vector_store,
            project_id=project_id,
            vector_size=settings.vector_size,
            top_k=body.top_k,
            embedding_model=settings.embedding_model,
        )
        matrix = build_trace_matrix(session=session, project_id=project_id)
    return {
        "generated": {
            "requirements_total": result.requirements_total,
            "requirements_with_links": result.requirements_with_links,
            "links_generated": result.links_generated,
        },
        "matrix_summary": {
            "completion_percentage": matrix["completion_percentage"],
            "coverage_percentage": matrix["coverage_percentage"],
        },
    }


@app.get("/api/projects/{project_id}/trace-matrix")
def get_trace_matrix(project_id: str) -> dict[str, object]:
    ensure_ready()
    with database.SessionLocal() as session:
        return build_trace_matrix(session=session, project_id=project_id)


@app.get("/api/projects/{project_id}/vectors/sample")
def sample_vectors(
    project_id: str,
    kind: str = "requirements",
    limit: int = 3,
) -> dict[str, object]:
    ensure_ready()
    if kind not in {"requirements", "code_units"}:
        raise HTTPException(status_code=400, detail="kind must be `requirements` or `code_units`")
    if limit < 1 or limit > 20:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 20")
    return {
        "project_id": project_id,
        "kind": kind,
        "samples": vector_store.sample_vectors(project_id=project_id, kind=kind, limit=limit),
    }


@app.post("/api/projects/{project_id}/reset")
def reset_project_data(project_id: str) -> dict[str, object]:
    ensure_ready()
    with database.SessionLocal() as session:
        deleted = reset_project(session=session, vector_store=vector_store, project_id=project_id)
        vectors = vector_store.count_points(project_id)
    return {
        "project_id": project_id,
        "deleted": deleted,
        "vector_counts": vectors,
    }
