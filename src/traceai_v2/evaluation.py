"""Evaluation harness for traceability link quality.

Computes standard IR and traceability metrics given predicted trace links
and a gold-standard reference. Designed for IEEE-compliant reporting.

Metrics computed:
- Precision@k, Recall@k, F1@k
- nDCG@k (Normalized Discounted Cumulative Gain)
- Hit@k (percentage of queries with at least one correct result)
- Mean Reciprocal Rank (MRR)
- Mean Average Precision (MAP)
- Coverage %
"""
from __future__ import annotations

import math
import csv
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

logger = logging.getLogger(__name__)


@dataclass
class GoldLink:
    """A single ground-truth trace link."""
    req_key: str
    code_key: str
    relevance: float = 1.0  # 1.0 = fully relevant, 0.5 = partially relevant


@dataclass
class PredictedLink:
    """A single predicted trace link."""
    req_key: str
    code_key: str
    score: float
    rank: int
    label: str


@dataclass
class RequirementMetrics:
    """Per-requirement evaluation results."""
    req_key: str
    precision_at_k: float = 0.0
    recall_at_k: float = 0.0
    f1_at_k: float = 0.0
    ndcg_at_k: float = 0.0
    reciprocal_rank: float = 0.0
    average_precision: float = 0.0
    has_correct_link: bool = False
    gold_count: int = 0
    predicted_count: int = 0


@dataclass
class EvaluationResult:
    """Aggregate evaluation results."""
    k: int = 5
    requirements_total: int = 0
    requirements_with_gold: int = 0

    # Macro-averaged metrics
    precision_at_k: float = 0.0
    recall_at_k: float = 0.0
    f1_at_k: float = 0.0
    ndcg_at_k: float = 0.0
    hit_at_k: float = 0.0
    mrr: float = 0.0
    map_score: float = 0.0
    coverage_pct: float = 0.0

    # Per-requirement breakdown
    per_requirement: list[RequirementMetrics] = field(default_factory=list)

    # Config info
    embedding_provider: str = ""
    embedding_model: str = ""
    parser_type: str = ""
    notes: str = ""


# ---------------------------------------------------------------------------
# Core metric computation
# ---------------------------------------------------------------------------


def evaluate(
    predicted: list[PredictedLink],
    gold: list[GoldLink],
    k: int = 5,
) -> EvaluationResult:
    """Compute all evaluation metrics.

    Args:
        predicted: Predicted trace links with scores and ranks.
        gold: Gold-standard trace links.
        k: Top-k cutoff for precision/recall.

    Returns:
        EvaluationResult with all metrics filled.
    """
    # Build gold index: req_key -> set of relevant code_keys
    gold_by_req: dict[str, set[str]] = {}
    for g in gold:
        gold_by_req.setdefault(g.req_key, set()).add(g.code_key)

    # Build predicted index: req_key -> list of (code_key, score, rank)
    pred_by_req: dict[str, list[PredictedLink]] = {}
    for p in predicted:
        pred_by_req.setdefault(p.req_key, []).append(p)

    # Sort predictions by rank for each requirement
    for req_key in pred_by_req:
        pred_by_req[req_key].sort(key=lambda p: p.rank)

    # All requirement keys (union of gold + predicted)
    all_req_keys = sorted(set(gold_by_req.keys()) | set(pred_by_req.keys()))

    per_req_metrics: list[RequirementMetrics] = []
    total_precision = 0.0
    total_recall = 0.0
    total_f1 = 0.0
    total_ndcg = 0.0
    total_rr = 0.0
    total_ap = 0.0
    covered = 0
    reqs_with_gold = 0

    for req_key in all_req_keys:
        gold_set = gold_by_req.get(req_key, set())
        preds = pred_by_req.get(req_key, [])
        top_k_preds = preds[:k]

        if not gold_set:
            per_req_metrics.append(RequirementMetrics(
                req_key=req_key,
                gold_count=0,
                predicted_count=len(top_k_preds),
            ))
            continue

        reqs_with_gold += 1

        # Precision@k and Recall@k
        relevant_in_top_k = sum(1 for p in top_k_preds if p.code_key in gold_set)
        precision = relevant_in_top_k / len(top_k_preds) if top_k_preds else 0.0
        recall = relevant_in_top_k / len(gold_set) if gold_set else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

        # nDCG@k — rewards correct results at higher ranks
        dcg = 0.0
        for i, p in enumerate(top_k_preds, start=1):
            rel = 1.0 if p.code_key in gold_set else 0.0
            dcg += rel / math.log2(i + 1)
        ideal_count = min(len(gold_set), k)
        idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_count + 1))
        ndcg = dcg / idcg if idcg > 0 else 0.0

        # Reciprocal Rank (rank of first relevant result)
        rr = 0.0
        for p in top_k_preds:
            if p.code_key in gold_set:
                rr = 1.0 / p.rank
                break

        # Average Precision
        ap = 0.0
        relevant_so_far = 0
        for i, p in enumerate(top_k_preds, start=1):
            if p.code_key in gold_set:
                relevant_so_far += 1
                ap += relevant_so_far / i
        if gold_set:
            ap /= min(len(gold_set), k)

        has_correct = relevant_in_top_k > 0

        m = RequirementMetrics(
            req_key=req_key,
            precision_at_k=precision,
            recall_at_k=recall,
            f1_at_k=f1,
            ndcg_at_k=ndcg,
            reciprocal_rank=rr,
            average_precision=ap,
            has_correct_link=has_correct,
            gold_count=len(gold_set),
            predicted_count=len(top_k_preds),
        )
        per_req_metrics.append(m)

        total_precision += precision
        total_recall += recall
        total_f1 += f1
        total_ndcg += ndcg
        total_rr += rr
        total_ap += ap
        if has_correct:
            covered += 1

    n = max(1, reqs_with_gold)
    return EvaluationResult(
        k=k,
        requirements_total=len(all_req_keys),
        requirements_with_gold=reqs_with_gold,
        precision_at_k=total_precision / n,
        recall_at_k=total_recall / n,
        f1_at_k=total_f1 / n,
        ndcg_at_k=total_ndcg / n,
        hit_at_k=(covered / n) * 100.0,
        mrr=total_rr / n,
        map_score=total_ap / n,
        coverage_pct=(covered / n) * 100.0,
        per_requirement=per_req_metrics,
    )


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------


def load_gold_links(csv_path: Union[str, Path]) -> list[GoldLink]:
    """Load gold standard links from CSV.

    Expected columns: req_key, code_key [, relevance]
    """
    path = Path(csv_path)
    links = []
    with path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            links.append(GoldLink(
                req_key=row["req_key"].strip(),
                code_key=row["code_key"].strip(),
                relevance=float(row.get("relevance", "1.0")),
            ))
    logger.info("Loaded %d gold links from %s", len(links), path)
    return links


def load_predicted_links_from_db(
    session,
    project_id: str,
) -> list[PredictedLink]:
    """Load predicted trace links from the database."""
    from traceai_v2.storage import TraceLinkRecord
    from sqlalchemy import select

    links = session.scalars(
        select(TraceLinkRecord)
        .where(TraceLinkRecord.project_id == project_id)
        .order_by(TraceLinkRecord.req_key, TraceLinkRecord.rank)
    ).all()

    return [
        PredictedLink(
            req_key=link.req_key,
            code_key=link.code_key,
            score=float(link.score),
            rank=int(link.rank),
            label=link.label,
        )
        for link in links
    ]


def format_results_table(result: EvaluationResult) -> str:
    """Format evaluation results as a readable table."""
    lines = [
        "=" * 60,
        f"  TraceAI Evaluation Results (k={result.k})",
        "=" * 60,
        "",
        f"  Requirements total:    {result.requirements_total}",
        f"  Requirements w/ gold:  {result.requirements_with_gold}",
        "",
        "  Aggregate Metrics:",
        f"  {'─' * 40}",
        f"  Precision@{result.k}:         {result.precision_at_k:.4f}",
        f"  Recall@{result.k}:            {result.recall_at_k:.4f}",
        f"  F1@{result.k}:               {result.f1_at_k:.4f}",
        f"  nDCG@{result.k}:             {result.ndcg_at_k:.4f}",
        f"  Hit@{result.k}:              {result.hit_at_k:.1f}%",
        f"  MRR:                  {result.mrr:.4f}",
        f"  MAP:                  {result.map_score:.4f}",
        f"  Coverage:             {result.coverage_pct:.1f}%",
        "",
    ]

    if result.embedding_provider:
        lines.append(f"  Config: provider={result.embedding_provider}, "
                     f"model={result.embedding_model}, parser={result.parser_type}")
        lines.append("")

    lines.append("  Per-Requirement Breakdown:")
    lines.append(f"  {'─' * 55}")
    lines.append(f"  {'Req':<10} {'P@k':<8} {'R@k':<8} {'F1@k':<8} {'RR':<8} {'Gold':<6} {'Hit'}")
    lines.append(f"  {'─' * 55}")
    for m in result.per_requirement:
        if m.gold_count == 0:
            continue
        hit = "✓" if m.has_correct_link else "✗"
        lines.append(
            f"  {m.req_key:<10} {m.precision_at_k:<8.4f} {m.recall_at_k:<8.4f} "
            f"{m.f1_at_k:<8.4f} {m.reciprocal_rank:<8.4f} {m.gold_count:<6} {hit}"
        )
    lines.append(f"  {'─' * 55}")
    lines.append("")
    if result.notes:
        lines.append(f"  Notes: {result.notes}")
    lines.append("=" * 60)

    return "\n".join(lines)


def save_results_json(result: EvaluationResult, path: Union[str, Path]) -> None:
    """Save evaluation results to JSON."""
    data = {
        "k": result.k,
        "requirements_total": result.requirements_total,
        "requirements_with_gold": result.requirements_with_gold,
        "precision_at_k": result.precision_at_k,
        "recall_at_k": result.recall_at_k,
        "f1_at_k": result.f1_at_k,
        "ndcg_at_k": result.ndcg_at_k,
        "hit_at_k": result.hit_at_k,
        "mrr": result.mrr,
        "map_score": result.map_score,
        "coverage_pct": result.coverage_pct,
        "config": {
            "embedding_provider": result.embedding_provider,
            "embedding_model": result.embedding_model,
            "parser_type": result.parser_type,
        },
        "per_requirement": [
            {
                "req_key": m.req_key,
                "precision_at_k": m.precision_at_k,
                "recall_at_k": m.recall_at_k,
                "f1_at_k": m.f1_at_k,
                "ndcg_at_k": m.ndcg_at_k,
                "reciprocal_rank": m.reciprocal_rank,
                "average_precision": m.average_precision,
                "has_correct_link": m.has_correct_link,
                "gold_count": m.gold_count,
            }
            for m in result.per_requirement
        ],
        "notes": result.notes,
    }
    Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")
    logger.info("Results saved to %s", path)
