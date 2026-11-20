from __future__ import annotations

import logging
import re
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import select

from .persistence import (
    build_impact_analysis,
    build_trace_matrix,
    create_project,
    generate_trace_links,
    get_all_projects,
    get_project,
    persist_code_units_csv,
    persist_requirements_csv,
    reset_project,
    update_project_counts,
    sync_changed_files,
    clear_project_trace_links,
)
from .csv_utils import configure_csv_field_limit
from .github_integration import GitHubRepoManager
from .repo_ingestion import LocalRepoIngestionPipeline, RepoIngestionError
from .requirements_ingestion import IngestionError, RequirementsIngestionPipeline
from .settings import load_settings
from .storage import CodeUnitRecord, ProjectRecord, RequirementRecord, AnalysisRunRecord, build_database, init_db
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

logger = logging.getLogger("traceai_v2.api")
startup_error: Optional[str] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global startup_error
    try:
        init_db(database)
        vector_store.ensure_collections()
        startup_error = None
    except Exception as exc:
        startup_error = str(exc)
        logger.exception("Failed to initialize startup dependencies: %s", exc)
    yield


app = FastAPI(title="TraceAI V2 API", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def ensure_ready() -> None:
    if startup_error:
        raise HTTPException(status_code=503, detail=f"Startup dependency error: {startup_error}")


@app.get("/health")
def health() -> dict[str, str]:
    if startup_error:
        return {"status": "degraded", "detail": startup_error}
    return {"status": "ok"}


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower().strip())
    return slug.strip("-")[:64]

class CreateProjectRequest(BaseModel):
    name: str
    description: str = ""
    repo_type: str = "local"
    repo_path: str = ""
    github_url: str = ""
    branch: str = "main"


class UpdateProjectRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


@app.post("/api/projects")
def create_project_endpoint(body: CreateProjectRequest) -> dict[str, object]:
    ensure_ready()
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Project name is required")
    project_id = _slugify(body.name)
    if not project_id:
        raise HTTPException(status_code=400, detail="Project name must contain alphanumeric characters")
    with database.SessionLocal() as session:
        existing = get_project(session=session, project_id=project_id)
        if existing:
            raise HTTPException(status_code=409, detail=f"Project '{project_id}' already exists")
        return create_project(
            session=session,
            project_id=project_id,
            name=body.name.strip(),
            description=body.description,
            repo_type=body.repo_type,
            repo_path=body.repo_path or None,
            github_url=body.github_url or None,
            branch=body.branch or None,
        )


@app.get("/api/projects")
def list_projects() -> list[dict[str, object]]:
    ensure_ready()
    with database.SessionLocal() as session:
        return get_all_projects(session=session)


@app.get("/api/projects/{project_id}")
def get_project_endpoint(project_id: str) -> dict[str, object]:
    ensure_ready()
    with database.SessionLocal() as session:
        project = get_project(session=session, project_id=project_id)
        if project is None:
            raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
        return project


@app.patch("/api/projects/{project_id}")
def update_project_endpoint(project_id: str, body: UpdateProjectRequest) -> dict[str, object]:
    ensure_ready()
    with database.SessionLocal() as session:
        record = session.scalars(
            select(ProjectRecord).where(ProjectRecord.project_id == project_id)
        ).first()
        if record is None:
            raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
        if body.name is not None:
            record.name = body.name.strip()
        if body.description is not None:
            record.description = body.description
        session.commit()
        project = get_project(session=session, project_id=project_id)
        if project is None:
            raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
        return project


@app.delete("/api/projects")
def delete_all_projects() -> dict[str, object]:
    ensure_ready()
    with database.SessionLocal() as session:
        projects = get_all_projects(session=session)
        count = 0
        for p in projects:
            pid = str(p["project_id"])
            reset_project(session=session, vector_store=vector_store, project_id=pid)
            count += 1
    return {"deleted_projects_count": count}

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
        update_project_counts(
            session=session,
            project_id=project_id,
            requirements_count=persist_result.inserted_requirements,
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
    repo_path: str = ""
    version: Optional[int] = None
    commit_sha: Optional[str] = None


@app.post("/api/projects/{project_id}/repo/ingest")
def ingest_repo(project_id: str, body: RepoIngestRequest) -> dict[str, object]:
    ensure_ready()
    repo_path = body.repo_path
    commit_sha = body.commit_sha

    with database.SessionLocal() as session:
        project_record = session.scalars(
            select(ProjectRecord).where(ProjectRecord.project_id == project_id)
        ).first()
        if not project_record:
            raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

        if project_record.repo_type == "github":
            github_url = project_record.github_url
            if not github_url:
                raise HTTPException(status_code=400, detail="GitHub URL is not configured for this project")
            branch = project_record.branch or "main"
            
            manager = GitHubRepoManager(settings.data_root)
            try:
                local_path = manager.clone_or_pull(github_url, branch)
                commit_sha = commit_sha or manager.get_latest_commit_sha(local_path)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"Git operation failed: {exc}") from exc
            
            repo_path = str(local_path)
        else:
            if not repo_path:
                repo_path = project_record.repo_path

    if not repo_path:
        raise HTTPException(status_code=400, detail="repo_path is required")

    try:
        ingest_result = repo_pipeline.ingest(
            project_id=project_id,
            repo_path=repo_path,
            version=body.version,
            commit_sha=commit_sha,
        )
    except RepoIngestionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    with database.SessionLocal() as session:
        record = session.scalars(
            select(ProjectRecord).where(ProjectRecord.project_id == project_id)
        ).first()
        if record and commit_sha:
            record.last_commit_sha = commit_sha

        persist_result = persist_code_units_csv(
            session=session,
            vector_store=vector_store,
            csv_path=str(ingest_result["processed_csv"]),
            vector_size=settings.vector_size,
            embedding_model=settings.embedding_model,
        )
        update_project_counts(
            session=session,
            project_id=project_id,
            code_units_count=persist_result.inserted_code_units,
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

    import time
    from datetime import datetime, timezone
    start_time = time.time()

    with database.SessionLocal() as session:
        project_record = session.scalars(select(ProjectRecord).where(ProjectRecord.project_id == project_id)).first()
        requirements_count = session.query(RequirementRecord).filter(RequirementRecord.project_id == project_id).count()
        code_units_count = session.query(CodeUnitRecord).filter(CodeUnitRecord.project_id == project_id).count()

        run_record = AnalysisRunRecord(
            project_id=project_id,
            commit_sha=project_record.last_commit_sha if project_record else None,
            changed_files="[]",
            requirements_count=requirements_count,
            code_units_count=code_units_count,
            trace_links_count=0,
            execution_time_seconds=0.0,
            created_at=datetime.now(timezone.utc),
        )
        session.add(run_record)
        session.flush()
        run_id = run_record.id

        result = generate_trace_links(
            session=session,
            vector_store=vector_store,
            project_id=project_id,
            run_id=run_id,
            vector_size=settings.vector_size,
            top_k=body.top_k,
            embedding_model=settings.embedding_model,
        )

        duration = round(time.time() - start_time, 2)
        run_record.trace_links_count = result.links_generated
        run_record.execution_time_seconds = duration

        if project_record:
            project_record.trace_links_count = result.links_generated
            project_record.code_units_count = code_units_count
            project_record.requirements_count = requirements_count
            project_record.last_run_at = datetime.now(timezone.utc)

        session.commit()
        matrix = build_trace_matrix(session=session, project_id=project_id, run_id=run_id)
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
def get_trace_matrix(project_id: str, run_id: Optional[int] = None) -> dict[str, object]:
    ensure_ready()
    with database.SessionLocal() as session:
        return build_trace_matrix(session=session, project_id=project_id, run_id=run_id)


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


@app.post("/api/projects/{project_id}/sync")
def sync_project(project_id: str) -> dict[str, object]:
    ensure_ready()
    import time
    import json
    from datetime import datetime, timezone

    start_time = time.time()

    with database.SessionLocal() as session:
        project_record = session.scalars(
            select(ProjectRecord).where(ProjectRecord.project_id == project_id)
        ).first()
        if not project_record:
            raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

        if project_record.repo_type != "github":
            raise HTTPException(status_code=400, detail="Only GitHub projects can be synced")

        github_url = project_record.github_url
        if not github_url:
            raise HTTPException(status_code=400, detail="GitHub URL is not configured for this project")

        branch = project_record.branch or "main"
        old_sha = project_record.last_commit_sha

        manager = GitHubRepoManager(settings.data_root)
        try:
            local_path = manager.clone_or_pull(github_url, branch)
            new_sha = manager.get_latest_commit_sha(local_path)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Git operation failed: {exc}") from exc

        if old_sha == new_sha:
            return {
                "changed_files": [],
                "old_commit": old_sha or "",
                "new_commit": new_sha,
                "reanalyzed": False,
                "message": "Already up to date."
            }

        try:
            if old_sha:
                changed_files = manager.get_commit_diff(local_path, old_sha, new_sha)
            else:
                changed_files = []
        except Exception:
            changed_files = []

        is_full_reanalysis = not changed_files

        if is_full_reanalysis:
            try:
                ingest_result = repo_pipeline.ingest(
                    project_id=project_id,
                    repo_path=str(local_path),
                    commit_sha=new_sha,
                )
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"Ingestion failed: {exc}") from exc

            persist_result = persist_code_units_csv(
                session=session,
                vector_store=vector_store,
                csv_path=str(ingest_result["processed_csv"]),
                vector_size=settings.vector_size,
                embedding_model=settings.embedding_model,
            )
            code_units_count = persist_result.inserted_code_units
        else:
            sync_changed_files(
                session=session,
                vector_store=vector_store,
                project_id=project_id,
                repo_root=local_path,
                changed_files=changed_files,
                commit_sha=new_sha,
                vector_size=settings.vector_size,
                embedding_model=settings.embedding_model,
            )
            code_units_count = session.query(CodeUnitRecord).filter(CodeUnitRecord.project_id == project_id).count()

        requirements_count = session.query(RequirementRecord).filter(RequirementRecord.project_id == project_id).count()

        run_record = AnalysisRunRecord(
            project_id=project_id,
            commit_sha=new_sha,
            changed_files=json.dumps(changed_files) if changed_files else "[]",
            requirements_count=requirements_count,
            code_units_count=code_units_count,
            trace_links_count=0,
            execution_time_seconds=0.0,
            created_at=datetime.now(timezone.utc),
        )
        session.add(run_record)
        session.flush()
        run_id = run_record.id

        trace_result = generate_trace_links(
            session=session,
            vector_store=vector_store,
            project_id=project_id,
            run_id=run_id,
            vector_size=settings.vector_size,
            embedding_model=settings.embedding_model,
        )

        trace_links_count = trace_result.links_generated
        duration = round(time.time() - start_time, 2)

        run_record.trace_links_count = trace_links_count
        run_record.execution_time_seconds = duration

        project_record.last_commit_sha = new_sha
        project_record.code_units_count = code_units_count
        project_record.trace_links_count = trace_links_count
        project_record.last_run_at = datetime.now(timezone.utc)

        session.commit()

        return {
            "changed_files": changed_files,
            "old_commit": old_sha or "",
            "new_commit": new_sha,
            "reanalyzed": True,
            "duration_seconds": duration,
            "counts": {
                "requirements": requirements_count,
                "code_units": code_units_count,
                "trace_links": trace_links_count,
            }
        }


@app.get("/api/projects/{project_id}/runs")
def list_runs(project_id: str) -> list[dict[str, object]]:
    ensure_ready()
    with database.SessionLocal() as session:
        records = session.scalars(
            select(AnalysisRunRecord)
            .where(AnalysisRunRecord.project_id == project_id)
            .order_by(AnalysisRunRecord.created_at.desc())
        ).all()
        return [
            {
                "id": r.id,
                "project_id": r.project_id,
                "commit_sha": r.commit_sha or "",
                "changed_files": r.changed_files or "[]",
                "requirements_count": r.requirements_count,
                "code_units_count": r.code_units_count,
                "trace_links_count": r.trace_links_count,
                "execution_time_seconds": r.execution_time_seconds,
                "created_at": r.created_at.isoformat(),
            }
            for r in records
        ]


@app.get("/api/projects/{project_id}/runs/{run_id}/requirements/{req_id}/explanation")
def get_explanation(project_id: str, run_id: int, req_id: str) -> dict[str, str]:
    ensure_ready()
    from .persistence import get_or_generate_explanation
    with database.SessionLocal() as session:
        explanation = get_or_generate_explanation(
            session=session,
            project_id=project_id,
            run_id=run_id,
            requirement_id=req_id,
        )
        return {"explanation": explanation}


@app.get("/api/projects/{project_id}/runs/{run_id}/export/csv")
def export_project_run_csv(project_id: str, run_id: int):
    ensure_ready()
    from .report_export import export_csv
    with database.SessionLocal() as session:
        project_record = session.scalars(select(ProjectRecord).where(ProjectRecord.project_id == project_id)).first()
        project_name = project_record.name if project_record else project_id

        actual_run_id = run_id
        if actual_run_id == 0:
            latest_run = session.scalars(
                select(AnalysisRunRecord)
                .where(AnalysisRunRecord.project_id == project_id)
                .order_by(AnalysisRunRecord.created_at.desc())
            ).first()
            if latest_run:
                actual_run_id = latest_run.id

        matrix = build_trace_matrix(session=session, project_id=project_id, run_id=actual_run_id)
        csv_buffer = export_csv(matrix, project_name)
        
        from fastapi.responses import StreamingResponse
        return StreamingResponse(
            iter([csv_buffer.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=traceability_{project_id}_run_{actual_run_id}.csv"}
        )


@app.get("/api/projects/{project_id}/runs/{run_id}/export/pdf")
def export_project_run_pdf(project_id: str, run_id: int):
    ensure_ready()
    from .report_export import export_pdf
    with database.SessionLocal() as session:
        project_record = session.scalars(select(ProjectRecord).where(ProjectRecord.project_id == project_id)).first()
        project_name = project_record.name if project_record else project_id

        actual_run_id = run_id
        if actual_run_id == 0:
            latest_run = session.scalars(
                select(AnalysisRunRecord)
                .where(AnalysisRunRecord.project_id == project_id)
                .order_by(AnalysisRunRecord.created_at.desc())
            ).first()
            if latest_run:
                actual_run_id = latest_run.id
        
        run_record = session.scalars(select(AnalysisRunRecord).where(AnalysisRunRecord.id == actual_run_id)).first()
        if not run_record:
            raise HTTPException(status_code=404, detail="Analysis run not found.")
            
        run_details = {
            "created_at": run_record.created_at.isoformat(),
            "commit_sha": run_record.commit_sha or "",
            "code_units_count": run_record.code_units_count,
        }
        
        matrix = build_trace_matrix(session=session, project_id=project_id, run_id=actual_run_id)
        pdf_buffer = export_pdf(matrix, project_name, run_details)
        
        from fastapi.responses import StreamingResponse
        return StreamingResponse(
            iter([pdf_buffer.getvalue()]),
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename=traceability_{project_id}_run_{actual_run_id}.pdf"}
        )


@app.get("/api/projects/{project_id}/impact")
def impact_analysis(project_id: str, file_path: str, run_id: int = 0):
    ensure_ready()
    with database.SessionLocal() as session:
        result = build_impact_analysis(
            session=session,
            project_id=project_id,
            file_path=file_path,
            run_id=run_id,
        )
        return result
