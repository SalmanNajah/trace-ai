from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .embeddings import embed_batch, embed_text
from .storage import CodeUnitRecord, ProjectRecord, RequirementRecord, TraceLinkRecord
from .vector_store import VectorStore


@dataclass
class PersistResult:
    inserted_requirements: int = 0
    inserted_code_units: int = 0
    requirement_vectors: int = 0
    code_vectors: int = 0


@dataclass
class TraceGenerationResult:
    requirements_total: int = 0
    requirements_with_links: int = 0
    links_generated: int = 0


def persist_requirements_csv(
    *,
    session: Session,
    vector_store: VectorStore,
    csv_path: str | Path,
    vector_size: int,
    embedding_model: str = "gemini-embedding-001",
) -> PersistResult:
    path = Path(csv_path)
    result = PersistResult()
    project_id = _project_id_from_csv(path)
    clear_project_requirements(session=session, vector_store=vector_store, project_id=project_id)

    rows_collected: list[dict[str, str]] = []
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            record = RequirementRecord(
                project_id=row["project_id"],
                requirement_id=row["requirement_id"],
                req_key=row["req_key"],
                text=row["text"],
                source_doc=row["source_doc"],
                version=int(row["version"]),
                created_at=_parse_dt(row["created_at"]),
            )
            session.add(record)
            rows_collected.append(row)
            result.inserted_requirements += 1

    texts = [row["text"] for row in rows_collected]
    vectors = embed_batch(
        texts,
        vector_size=vector_size,
        model=embedding_model,
        task_type="RETRIEVAL_DOCUMENT",
    )

    for row, vector in zip(rows_collected, vectors):
        vector_store.upsert_requirement(
            requirement_id=row["requirement_id"],
            vector=vector,
            payload={
                "project_id": row["project_id"],
                "req_key": row["req_key"],
                "source_doc": row["source_doc"],
                "version": int(row["version"]),
            },
        )
        result.requirement_vectors += 1

    session.commit()
    return result


def persist_code_units_csv(
    *,
    session: Session,
    vector_store: VectorStore,
    csv_path: str | Path,
    vector_size: int,
    embedding_model: str = "gemini-embedding-001",
) -> PersistResult:
    path = Path(csv_path)
    result = PersistResult()
    project_id = _project_id_from_csv(path)
    clear_project_code_units(session=session, vector_store=vector_store, project_id=project_id)

    # First pass: insert DB records and collect texts for batch embedding
    rows_collected: list[dict[str, str]] = []
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            record = CodeUnitRecord(
                project_id=row["project_id"],
                code_unit_id=row["code_unit_id"],
                code_key=row["code_key"],
                file_path=row["file_path"],
                symbol=row["symbol"],
                start_line=int(row["start_line"]),
                end_line=int(row["end_line"]),
                language=row["language"],
                chunk_type=row["chunk_type"],
                content=row["content"],
                commit_sha=row["commit_sha"] or None,
                created_at=_parse_dt(row["created_at"]),
            )
            session.add(record)
            rows_collected.append(row)
            result.inserted_code_units += 1

    # Batch embed all code content at once (100 per API call)
    texts = [row["content"] for row in rows_collected]
    vectors = embed_batch(
        texts,
        vector_size=vector_size,
        model=embedding_model,
        task_type="RETRIEVAL_DOCUMENT",
    )

    # Upsert vectors
    for row, vector in zip(rows_collected, vectors):
        vector_store.upsert_code_unit(
            code_unit_id=row["code_unit_id"],
            vector=vector,
            payload={
                "project_id": row["project_id"],
                "code_key": row["code_key"],
                "file_path": row["file_path"],
                "symbol": row["symbol"],
                "language": row["language"],
                "chunk_type": row["chunk_type"],
            },
        )
        result.code_vectors += 1

    session.commit()
    return result


def generate_trace_links(
    *,
    session: Session,
    vector_store: VectorStore,
    project_id: str,
    run_id: int,
    vector_size: int,
    top_k: int = 5,
    embedding_model: str = "gemini-embedding-001",
) -> TraceGenerationResult:
    from traceai_v2.reranker import rerank_candidates, is_available as reranker_available

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
        return TraceGenerationResult(requirements_total=len(requirements), requirements_with_links=0, links_generated=0)

    code_index = {item.code_unit_id: item for item in code_units}
    generated = 0
    req_with_links = 0
    now = datetime.now(timezone.utc)

    # Retrieve more candidates if reranker is available
    use_reranker = reranker_available()
    retrieve_k = top_k * 10 if use_reranker else top_k * 5  # 100 chunks

    # Build BM25 index for hybrid retrieval
    from traceai_v2.bm25_index import BM25Index
    bm25 = BM25Index()
    for cu in code_units:
        # Index filename + content for keyword matching
        doc_text = f"{cu.file_path} {cu.code_key} {cu.content}"
        bm25.add_document(cu.code_unit_id, doc_text)
    bm25.build()

    # Build req_key -> requirement index for query expansion
    req_index = {r.req_key: r for r in requirements}

    links_to_add: list[TraceLinkRecord] = []
    best_links: list[tuple[TraceLinkRecord, str, str]] = []

    for requirement in requirements:
        # Query expansion: for exception flows, prepend parent UC text + domain keywords
        query_text = requirement.text
        rk = requirement.req_key
        if "E" in rk:
            # Extract parent key (e.g., UC10E1 -> UC10, UC3E2 -> UC3)
            import re as _re
            parent_match = _re.match(r"(UC\d+)", rk)
            if parent_match:
                parent_key = parent_match.group(1)
                # Find any S-flow or base requirement for context
                for suffix in ["S1", "S2", "S3", ""]:
                    parent = req_index.get(f"{parent_key}{suffix}")
                    if parent:
                        query_text = (
                            f"{parent.text} "
                            f"Exception handling: {requirement.text}"
                        )
                        break

        req_vector = embed_text(
            query_text,
            vector_size=vector_size,
            model=embedding_model,
            task_type="RETRIEVAL_QUERY",
        )
        semantic_candidates = vector_store.search_code_units(
            project_id=project_id,
            query_vector=req_vector,
            limit=max(1, retrieve_k),
        )

        # BM25 keyword search
        bm25_candidates = bm25.search(query_text, limit=retrieve_k)

        # Reciprocal Rank Fusion (RRF) to merge semantic + BM25
        rrf_k = 60  # standard RRF constant
        rrf_scores: dict[str, float] = {}
        for rank_i, c in enumerate(semantic_candidates, start=1):
            rrf_scores[c["id"]] = rrf_scores.get(c["id"], 0) + 1.0 / (rrf_k + rank_i)
        for rank_i, c in enumerate(bm25_candidates, start=1):
            rrf_scores[c["id"]] = rrf_scores.get(c["id"], 0) + 1.0 / (rrf_k + rank_i)

        # Build merged candidate list — preserve original embed score for display
        all_candidate_ids = set(c["id"] for c in semantic_candidates) | set(c["id"] for c in bm25_candidates)
        semantic_map = {c["id"]: c for c in semantic_candidates}
        bm25_map = {c["id"]: c for c in bm25_candidates}
        candidates = []
        for cid in all_candidate_ids:
            base = semantic_map.get(cid, bm25_map.get(cid, {}))
            orig_score = base.get("score", 0)  # original embedding similarity (0-1)
            candidates.append({
                **base,
                "id": cid,
                "score": rrf_scores.get(cid, 0),  # RRF for ranking
                "embed_score": orig_score,          # original for display/labeling
            })
        candidates.sort(key=lambda x: x["score"], reverse=True)

        # Multi-chunk reranking: rerank individual chunks, then aggregate per file
        if use_reranker and candidates:
            # Take top candidates for reranking (limit to avoid slowness)
            rerank_pool = candidates[:top_k * 8]  # ~80 chunks

            enriched = []
            for c in rerank_pool:
                cu = code_index.get(c["id"])
                if cu is None:
                    continue
                from pathlib import Path as _Path
                fname = _Path(cu.file_path).name
                # Give reranker: filename + chunk content
                rerank_text = f"File: {fname}\n{cu.content}"
                enriched.append({
                    **c,
                    "code_key": cu.code_key,
                    "code_text": rerank_text[:2000],
                    "file_path": cu.file_path,
                })

            # Rerank all chunks individually
            from traceai_v2.reranker import rerank_candidates as _rerank
            reranked_chunks = _rerank(query_text, enriched, top_k=len(enriched))

            # Aggregate per file: take MAX reranker score per file
            best_per_file: dict[str, dict] = {}
            for c in reranked_chunks:
                fp = c.get("file_path", "")
                if not fp:
                    continue
                if fp not in best_per_file or c["score"] > best_per_file[fp]["score"]:
                    best_per_file[fp] = c
            candidates = sorted(best_per_file.values(), key=lambda x: x["score"], reverse=True)
        else:
            # No reranker: file-level dedup only
            if candidates:
                seen_files: dict[str, dict] = {}
                for c in candidates:
                    cu = code_index.get(c["id"])
                    if cu is None:
                        continue
                    fp = cu.file_path
                    if fp not in seen_files or c["score"] > seen_files[fp]["score"]:
                        seen_files[fp] = c
                candidates = sorted(seen_files.values(), key=lambda x: x["score"], reverse=True)

        if candidates:
            req_with_links += 1

        for rank, candidate in enumerate(candidates[:top_k], start=1):
            code_unit = code_index.get(candidate["id"])
            if code_unit is None:
                continue
            # Use the original embedding score for labeling (calibrated 0-1)
            # The reranker only changes ordering, not confidence
            score_val = candidate.get("embed_score")
            display_score = float(score_val) if score_val is not None else float(candidate["score"])
            label = _score_to_label(display_score)
            # Only store links with meaningful confidence (Partial or Implemented)
            if label == "Missing":
                continue
            explanation = (
                f"Semantic match between requirement `{requirement.req_key}` and "
                f"`{code_unit.file_path}:{code_unit.start_line}-{code_unit.end_line}`"
            )
            link_record = TraceLinkRecord(
                project_id=project_id,
                run_id=run_id,
                requirement_id=requirement.requirement_id,
                req_key=requirement.req_key,
                code_unit_id=code_unit.code_unit_id,
                code_key=code_unit.code_key,
                score=display_score,
                rank=rank,
                label=label,
                explanation=explanation,
                created_at=now,
            )
            links_to_add.append(link_record)
            generated += 1

    for link in links_to_add:
        session.add(link)

    session.commit()
    return TraceGenerationResult(
        requirements_total=len(requirements),
        requirements_with_links=req_with_links,
        links_generated=generated,
    )


def build_trace_matrix(*, session: Session, project_id: str, run_id: int | None = None) -> dict[str, object]:
    requirements = session.scalars(
        select(RequirementRecord)
        .where(RequirementRecord.project_id == project_id)
        .order_by(RequirementRecord.id)
    ).all()

    # Determine specific run_id if not passed
    actual_run_id = run_id
    if actual_run_id is None or actual_run_id == 0:
        from .storage import AnalysisRunRecord
        latest_run = session.scalars(
            select(AnalysisRunRecord)
            .where(AnalysisRunRecord.project_id == project_id)
            .order_by(AnalysisRunRecord.created_at.desc())
        ).first()
        if latest_run:
            actual_run_id = latest_run.id

    if actual_run_id is not None:
        links = session.scalars(
            select(TraceLinkRecord)
            .where(TraceLinkRecord.project_id == project_id, TraceLinkRecord.run_id == actual_run_id)
            .order_by(TraceLinkRecord.requirement_id, TraceLinkRecord.rank)
        ).all()
    else:
        links = session.scalars(
            select(TraceLinkRecord)
            .where(TraceLinkRecord.project_id == project_id)
            .order_by(TraceLinkRecord.requirement_id, TraceLinkRecord.rank)
        ).all()

    code_units = session.scalars(
        select(CodeUnitRecord)
        .where(CodeUnitRecord.project_id == project_id)
        .order_by(CodeUnitRecord.id)
    ).all()
    code_index = {item.code_unit_id: item for item in code_units}

    links_by_requirement: dict[str, list[TraceLinkRecord]] = {}
    for link in links:
        links_by_requirement.setdefault(link.requirement_id, []).append(link)

    rows: list[dict[str, object]] = []
    linked_requirements = 0
    implemented_requirements = 0
    for requirement in requirements:
        req_links = links_by_requirement.get(requirement.requirement_id, [])
        req_links_sorted = sorted(req_links, key=lambda item: item.rank)
        best_score = req_links_sorted[0].score if req_links_sorted else 0.0
        best_label = req_links_sorted[0].label if req_links_sorted else "Missing"
        if req_links_sorted:
            linked_requirements += 1
        if best_label == "Implemented":
            implemented_requirements += 1

        links_data = []
        for link in req_links_sorted:
            cu = code_index.get(link.code_unit_id)
            links_data.append(
                {
                    "code_unit_id": link.code_unit_id,
                    "code_key": link.code_key,
                    "score": link.score,
                    "rank": link.rank,
                    "label": link.label,
                    "explanation": link.explanation,
                    "file_path": cu.file_path if cu else "",
                    "symbol": cu.symbol if cu else "",
                    "start_line": cu.start_line if cu else 0,
                    "end_line": cu.end_line if cu else 0,
                    "content": cu.content if cu else "",
                }
            )

        rows.append(
            {
                "requirement_id": requirement.requirement_id,
                "req_key": requirement.req_key,
                "text": requirement.text,
                "best_label": best_label,
                "best_score": best_score,
                "links": links_data,
            }
        )

    total = len(requirements)
    completion_percentage = round((implemented_requirements / total) * 100, 2) if total else 0.0
    coverage_percentage = round((linked_requirements / total) * 100, 2) if total else 0.0
    return {
        "project_id": project_id,
        "requirements_total": total,
        "requirements_linked": linked_requirements,
        "requirements_implemented": implemented_requirements,
        "completion_percentage": completion_percentage,
        "coverage_percentage": coverage_percentage,
        "rows": rows,
    }


def clear_project_requirements(*, session: Session, vector_store: VectorStore, project_id: str) -> None:
    session.execute(delete(TraceLinkRecord).where(TraceLinkRecord.project_id == project_id))
    session.execute(delete(RequirementRecord).where(RequirementRecord.project_id == project_id))
    session.commit()
    vector_store.delete_requirement_vectors(project_id)


def clear_project_code_units(*, session: Session, vector_store: VectorStore, project_id: str) -> None:
    session.execute(delete(TraceLinkRecord).where(TraceLinkRecord.project_id == project_id))
    session.execute(delete(CodeUnitRecord).where(CodeUnitRecord.project_id == project_id))
    session.commit()
    vector_store.delete_code_vectors(project_id)


def clear_project_trace_links(*, session: Session, project_id: str) -> None:
    session.execute(delete(TraceLinkRecord).where(TraceLinkRecord.project_id == project_id))
    session.commit()


def reset_project(*, session: Session, vector_store: VectorStore, project_id: str) -> dict[str, int]:
    req_deleted = session.query(RequirementRecord).filter(RequirementRecord.project_id == project_id).count()
    code_deleted = session.query(CodeUnitRecord).filter(CodeUnitRecord.project_id == project_id).count()
    links_deleted = session.query(TraceLinkRecord).filter(TraceLinkRecord.project_id == project_id).count()
    session.execute(delete(TraceLinkRecord).where(TraceLinkRecord.project_id == project_id))
    session.execute(delete(RequirementRecord).where(RequirementRecord.project_id == project_id))
    session.execute(delete(CodeUnitRecord).where(CodeUnitRecord.project_id == project_id))
    session.execute(delete(ProjectRecord).where(ProjectRecord.project_id == project_id))
    session.commit()
    vector_store.delete_requirement_vectors(project_id)
    vector_store.delete_code_vectors(project_id)
    return {
        "requirements_deleted": req_deleted,
        "code_units_deleted": code_deleted,
        "trace_links_deleted": links_deleted,
    }


def _project_id_from_csv(path: Path) -> str:
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        first = next(reader, None)
        if first is None:
            raise ValueError(f"No rows found in CSV: {path}")
        return first["project_id"]


def _score_to_label(score: float) -> str:
    """Map embedding similarity score to trace label.

    Thresholds calibrated for BAAI/bge-base-en-v1.5 on cross-domain
    NL→code matching. The domain gap (natural language vs code) means
    cosine similarity tops out around 0.65-0.70 for strong matches.
    """
    if score >= 0.50:
        return "Implemented"
    if score >= 0.38:
        return "Partial"
    return "Missing"


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def get_all_projects(*, session: Session) -> list[dict[str, object]]:
    records = session.scalars(
        select(ProjectRecord).order_by(ProjectRecord.last_run_at.desc().nullslast(), ProjectRecord.created_at.desc())
    ).all()
    return [
        _project_to_dict(p)
        for p in records
    ]


def get_project(*, session: Session, project_id: str) -> dict[str, object] | None:
    record = session.scalars(
        select(ProjectRecord).where(ProjectRecord.project_id == project_id)
    ).first()
    if record is None:
        return None
    return _project_to_dict(record)


def create_project(
    *,
    session: Session,
    project_id: str,
    name: str,
    description: str = "",
    repo_type: str = "local",
    repo_path: str | None = None,
    github_url: str | None = None,
    branch: str | None = None,
) -> dict[str, object]:
    now = datetime.now(timezone.utc)
    record = ProjectRecord(
        project_id=project_id,
        name=name,
        description=description or None,
        repo_type=repo_type,
        repo_path=repo_path,
        github_url=github_url,
        branch=branch,
        created_at=now,
    )
    session.add(record)
    session.commit()
    return _project_to_dict(record)


def update_project_counts(
    *,
    session: Session,
    project_id: str,
    requirements_count: int | None = None,
    code_units_count: int | None = None,
    trace_links_count: int | None = None,
) -> None:
    record = session.scalars(
        select(ProjectRecord).where(ProjectRecord.project_id == project_id)
    ).first()
    if record is None:
        return
    if requirements_count is not None:
        record.requirements_count = requirements_count
    if code_units_count is not None:
        record.code_units_count = code_units_count
    if trace_links_count is not None:
        record.trace_links_count = trace_links_count
        record.last_run_at = datetime.now(timezone.utc)
    session.commit()


def _project_to_dict(p: ProjectRecord) -> dict[str, object]:
    return {
        "project_id": p.project_id,
        "name": p.name,
        "description": p.description or "",
        "repo_type": p.repo_type,
        "repo_path": p.repo_path or "",
        "github_url": p.github_url or "",
        "branch": p.branch or "",
        "last_commit_sha": p.last_commit_sha or "",
        "requirements_count": p.requirements_count,
        "code_units_count": p.code_units_count,
        "trace_links_count": p.trace_links_count,
        "created_at": p.created_at.isoformat() if p.created_at else None,
        "last_run": p.last_run_at.isoformat() if p.last_run_at else None,
    }


def sync_changed_files(
    *,
    session: Session,
    vector_store: VectorStore,
    project_id: str,
    repo_root: Path,
    changed_files: list[str],
    commit_sha: str,
    vector_size: int,
    embedding_model: str = "gemini-embedding-001",
) -> int:
    from .repo_ingestion import LocalRepoIngestionPipeline
    import uuid

    repo_pipeline = LocalRepoIngestionPipeline(repo_root.parent)
    now = datetime.now(timezone.utc)
    updated_count = 0

    max_key = session.scalars(
        select(CodeUnitRecord.code_key)
        .where(CodeUnitRecord.project_id == project_id)
        .order_by(CodeUnitRecord.id.desc())
    ).first()

    start_idx = 1
    if max_key and max_key.startswith("CODE-"):
        try:
            start_idx = int(max_key.split("-")[1]) + 1
        except Exception:
            pass

    for rel_path_str in changed_files:
        rel_path = Path(rel_path_str)
        if repo_pipeline._is_excluded(repo_root / rel_path, repo_root):
            continue

        extension = rel_path.suffix.lower()
        language = repo_pipeline.SUPPORTED_EXTENSIONS.get(extension)
        if language is None:
            continue

        session.execute(
            delete(CodeUnitRecord)
            .where(CodeUnitRecord.project_id == project_id, CodeUnitRecord.file_path == rel_path_str)
        )
        vector_store.delete_code_units_by_file(project_id, rel_path_str)

        file_abs_path = repo_root / rel_path
        if file_abs_path.exists() and file_abs_path.is_file():
            if (file_abs_path.stat().st_size / (1024 * 1024)) > repo_pipeline.MAX_FILE_SIZE_MB:
                continue

            try:
                source = file_abs_path.read_text(encoding="utf-8", errors="ignore")
                extracted = repo_pipeline._extract_for_file(rel_path_str, language, source)
            except Exception:
                continue

            if not extracted:
                continue

            new_records = []
            for entry in extracted:
                record = CodeUnitRecord(
                    project_id=project_id,
                    code_unit_id=str(uuid.uuid4()),
                    code_key=f"CODE-{start_idx:03d}",
                    file_path=rel_path_str,
                    symbol=entry["symbol"],
                    start_line=entry["start_line"],
                    end_line=entry["end_line"],
                    language=language,
                    chunk_type=entry["chunk_type"],
                    content=entry["content"],
                    commit_sha=commit_sha,
                    created_at=now,
                )
                session.add(record)
                new_records.append(record)
                start_idx += 1

            if new_records:
                texts = [r.content for r in new_records]
                vectors = embed_batch(
                    texts,
                    vector_size=vector_size,
                    model=embedding_model,
                    task_type="RETRIEVAL_DOCUMENT",
                )
                for r, vector in zip(new_records, vectors):
                    vector_store.upsert_code_unit(
                        code_unit_id=r.code_unit_id,
                        vector=vector,
                        payload={
                            "project_id": r.project_id,
                            "code_key": r.code_key,
                            "file_path": r.file_path,
                            "symbol": r.symbol,
                            "language": r.language,
                            "chunk_type": r.chunk_type,
                        },
                    )
                updated_count += len(new_records)

    session.commit()
    return updated_count


def get_or_generate_explanation(
    *,
    session: Session,
    project_id: str,
    run_id: int,
    requirement_id: str,
) -> str:
    """Load or generate a natural language explanation for a requirement-to-code trace link.

    Caches explanations by reusing previously generated explanations for the same requirement-code unit pair.
    """
    actual_run_id = run_id
    if actual_run_id is None or actual_run_id == 0:
        from .storage import AnalysisRunRecord
        latest_run = session.scalars(
            select(AnalysisRunRecord)
            .where(AnalysisRunRecord.project_id == project_id)
            .order_by(AnalysisRunRecord.created_at.desc())
        ).first()
        if latest_run:
            actual_run_id = latest_run.id

    link = session.scalars(
        select(TraceLinkRecord)
        .where(
            TraceLinkRecord.project_id == project_id,
            TraceLinkRecord.run_id == actual_run_id,
            TraceLinkRecord.requirement_id == requirement_id,
            TraceLinkRecord.rank == 1,
        )
    ).first()

    if not link:
        return "No trace link found."

    # If already generated
    if link.explanation and not link.explanation.startswith("Semantic match between requirement"):
        return link.explanation

    # Check database cache for any matching requirement + code_unit pair that has an explanation
    cached_link = session.scalars(
        select(TraceLinkRecord)
        .where(
            TraceLinkRecord.requirement_id == requirement_id,
            TraceLinkRecord.code_unit_id == link.code_unit_id,
            ~TraceLinkRecord.explanation.like("Semantic match between requirement%")
        )
        .limit(1)
    ).first()

    if cached_link and cached_link.explanation:
        link.explanation = cached_link.explanation
        session.commit()
        return link.explanation

    # Query Gemini on-demand
    requirement = session.scalars(
        select(RequirementRecord)
        .where(RequirementRecord.project_id == project_id, RequirementRecord.requirement_id == requirement_id)
    ).first()

    code_unit = session.scalars(
        select(CodeUnitRecord)
        .where(CodeUnitRecord.project_id == project_id, CodeUnitRecord.code_unit_id == link.code_unit_id)
    ).first()

    if not requirement or not code_unit:
        return link.explanation

    from traceai_v2.explainer import generate_batch_explanations
    batch_items = [{
        "id": 0,
        "requirement": requirement.text,
        "file_path": link.code_key,
        "code_snippet": code_unit.content,
    }]

    try:
        explanations = generate_batch_explanations(batch_items)
        if explanations and explanations[0]:
            exp_text = explanations[0].strip()
            link.explanation = exp_text
            session.commit()
            return exp_text
    except Exception as exc:
        logger.warning("Failed to generate lazy explanation: %s", exc)

    return link.explanation


def build_impact_analysis(
    *,
    session: Session,
    project_id: str,
    file_path: str,
    run_id: int | None = None,
) -> dict[str, object]:
    from .storage import AnalysisRunRecord

    actual_run_id = run_id
    if actual_run_id is None or actual_run_id == 0:
        latest = session.scalars(
            select(AnalysisRunRecord)
            .where(AnalysisRunRecord.project_id == project_id)
            .order_by(AnalysisRunRecord.created_at.desc())
        ).first()
        if latest:
            actual_run_id = latest.id

    code_units = session.scalars(
        select(CodeUnitRecord).where(
            CodeUnitRecord.project_id == project_id,
            CodeUnitRecord.file_path == file_path,
        )
    ).all()

    if not code_units:
        return {
            "file_path": file_path,
            "affected_requirements": [],
            "risk_level": "low",
            "affected_count": 0,
        }

    code_unit_ids = [cu.code_unit_id for cu in code_units]

    links = session.scalars(
        select(TraceLinkRecord).where(
            TraceLinkRecord.project_id == project_id,
            TraceLinkRecord.run_id == actual_run_id,
            TraceLinkRecord.code_unit_id.in_(code_unit_ids),
        )
    ).all()

    req_best: dict[str, dict] = {}
    for link in links:
        existing = req_best.get(link.requirement_id)
        if existing is None or link.score > existing["score"]:
            req_best[link.requirement_id] = {
                "requirement_id": link.requirement_id,
                "req_key": link.req_key,
                "score": link.score,
                "label": link.label,
                "code_key": link.code_key,
            }

    req_ids = list(req_best.keys())
    if req_ids:
        reqs = session.scalars(
            select(RequirementRecord).where(
                RequirementRecord.project_id == project_id,
                RequirementRecord.requirement_id.in_(req_ids),
            )
        ).all()
        req_text_map = {r.requirement_id: r.text for r in reqs}
    else:
        req_text_map = {}

    affected = []
    for rid, info in req_best.items():
        affected.append({
            "requirement_id": rid,
            "req_key": info["req_key"],
            "text": req_text_map.get(rid, ""),
            "score": round(info["score"], 4),
            "label": info["label"],
            "code_key": info["code_key"],
        })

    affected.sort(key=lambda x: x["score"], reverse=True)

    count = len(affected)
    if count > 3:
        risk_level = "high"
    elif count >= 1:
        risk_level = "medium"
    else:
        risk_level = "low"

    return {
        "file_path": file_path,
        "affected_requirements": affected,
        "risk_level": risk_level,
        "affected_count": count,
    }
