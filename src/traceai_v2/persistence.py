from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .embeddings import embed_batch, embed_text
from .storage import CodeUnitRecord, RequirementRecord, TraceLinkRecord
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
        clear_project_trace_links(session=session, project_id=project_id)
        return TraceGenerationResult(requirements_total=len(requirements), requirements_with_links=0, links_generated=0)

    code_index = {item.code_unit_id: item for item in code_units}
    clear_project_trace_links(session=session, project_id=project_id)
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
            display_score = float(candidate.get("embed_score", candidate["score"]))
            label = _score_to_label(display_score)
            # Only store links with meaningful confidence (Partial or Implemented)
            if label == "Missing":
                continue
            explanation = (
                f"Semantic match between requirement `{requirement.req_key}` and "
                f"`{code_unit.file_path}:{code_unit.start_line}-{code_unit.end_line}`"
            )
            session.add(
                TraceLinkRecord(
                    project_id=project_id,
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
            )
            generated += 1

    session.commit()
    return TraceGenerationResult(
        requirements_total=len(requirements),
        requirements_with_links=req_with_links,
        links_generated=generated,
    )


def build_trace_matrix(*, session: Session, project_id: str) -> dict[str, object]:
    requirements = session.scalars(
        select(RequirementRecord)
        .where(RequirementRecord.project_id == project_id)
        .order_by(RequirementRecord.id)
    ).all()
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
        best_score = float(req_links_sorted[0].score) if req_links_sorted else 0.0
        best_label = req_links_sorted[0].label if req_links_sorted else "Missing"
        if req_links_sorted:
            linked_requirements += 1
        if best_label == "Implemented":
            implemented_requirements += 1

        rows.append(
            {
                "requirement_id": requirement.requirement_id,
                "req_key": requirement.req_key,
                "text": requirement.text,
                "best_label": best_label,
                "best_score": best_score,
                "links": [
                    {
                        "code_unit_id": link.code_unit_id,
                        "code_key": link.code_key,
                        "score": float(link.score),
                        "rank": link.rank,
                        "label": link.label,
                        "explanation": link.explanation,
                        "file_path": code_index.get(link.code_unit_id).file_path if code_index.get(link.code_unit_id) else "",
                        "symbol": code_index.get(link.code_unit_id).symbol if code_index.get(link.code_unit_id) else "",
                        "start_line": code_index.get(link.code_unit_id).start_line if code_index.get(link.code_unit_id) else 0,
                        "end_line": code_index.get(link.code_unit_id).end_line if code_index.get(link.code_unit_id) else 0,
                        "content": code_index.get(link.code_unit_id).content if code_index.get(link.code_unit_id) else "",
                    }
                    for link in req_links_sorted
                ],
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
    from sqlalchemy import func
    stmt = (
        select(TraceLinkRecord.project_id, func.max(TraceLinkRecord.created_at).label("last_run"))
        .group_by(TraceLinkRecord.project_id)
        .order_by(func.max(TraceLinkRecord.created_at).desc())
    )
    results = session.execute(stmt).all()
    
    projects = []
    for pid, last_run in results:
        projects.append({
            "project_id": pid,
            "name": pid,  # Use project_id as name for now until Auth/Projects table is added
            "last_run": last_run.isoformat() if last_run else None,
        })
    return projects
