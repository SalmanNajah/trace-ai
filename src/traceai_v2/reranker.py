"""Reranker module — local cross-encoder with optional Gemini fallback.

Stage 2 of the retrieval pipeline. Takes top-N embedding candidates
and reranks them using a cross-encoder that reads (requirement, code)
pairs together for deeper semantic matching.

Primary: Local cross-encoder (ms-marco-MiniLM, ~80MB, runs on M4)
Backup:  Gemini API (when local model unavailable)
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Local cross-encoder (primary)
# ---------------------------------------------------------------------------

_cross_encoder = None
_CROSS_ENCODER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"


def _get_cross_encoder():
    global _cross_encoder
    if _cross_encoder is not None:
        return _cross_encoder
    try:
        from sentence_transformers import CrossEncoder
        logger.info("Loading cross-encoder: %s ...", _CROSS_ENCODER_MODEL)
        try:
            _cross_encoder = CrossEncoder(_CROSS_ENCODER_MODEL, local_files_only=True)
        except Exception:
            _cross_encoder = CrossEncoder(_CROSS_ENCODER_MODEL)
        logger.info("Cross-encoder loaded: %s", _CROSS_ENCODER_MODEL)
        return _cross_encoder
    except Exception as exc:
        logger.warning("Cross-encoder unavailable: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Gemini reranker (backup)
# ---------------------------------------------------------------------------

_gemini_client = None
_gemini_available: Optional[bool] = None


def _get_gemini_client():
    global _gemini_client, _gemini_available
    if _gemini_available is not None:
        return _gemini_client
    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key or api_key in ("your_gemini_api_key_here", "PASTE_YOUR_KEY_HERE"):
        _gemini_available = False
        return None
    try:
        from google import genai
        _gemini_client = genai.Client(api_key=api_key)
        _gemini_available = True
        return _gemini_client
    except Exception as exc:
        logger.warning("Gemini reranker unavailable: %s", exc)
        _gemini_available = False
        return None


def _gemini_rerank(requirement_text: str, candidates: list[dict], top_k: int) -> list[dict]:
    """Rerank using Gemini LLM judgement."""
    client = _get_gemini_client()
    if client is None:
        return candidates[:top_k]

    sections = []
    for i, c in enumerate(candidates):
        snippet = c.get("code_text", "")[:800]
        sections.append(f"[{i}] {c.get('code_key', '')}:\n```\n{snippet}\n```")

    prompt = (
        "You are a software traceability expert. Rate each candidate code file's "
        "relevance to the requirement (0-10).\n\n"
        f"REQUIREMENT:\n{requirement_text}\n\n"
        f"CANDIDATES:\n" + "\n\n".join(sections) + "\n\n"
        "Respond ONLY with comma-separated scores. Example: 8,3,7,0,5"
    )

    try:
        response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
        scores = []
        for s in response.text.strip().split(","):
            try:
                scores.append(int(s.strip()))
            except ValueError:
                scores.append(0)
        while len(scores) < len(candidates):
            scores.append(0)

        reranked = []
        for i, c in enumerate(candidates):
            llm_score = min(scores[i], 10) / 10.0
            combined = 0.7 * llm_score + 0.3 * c.get("score", 0)
            reranked.append({**c, "score": combined})
        reranked.sort(key=lambda x: x["score"], reverse=True)
        return reranked[:top_k]
    except Exception as exc:
        logger.warning("Gemini rerank failed: %s — using embedding scores", exc)
        return candidates[:top_k]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def rerank_candidates(
    requirement_text: str,
    candidates: list[dict],
    top_k: int = 10,
) -> list[dict]:
    """Rerank candidates using local cross-encoder or Gemini fallback.

    Args:
        requirement_text: The requirement text
        candidates: List with keys: code_key, code_text, score, id
        top_k: Number of results to return

    Returns:
        Reranked list of candidates with updated scores
    """
    if not candidates:
        return []

    # Try local cross-encoder first
    encoder = _get_cross_encoder()
    if encoder is not None:
        pairs = [(requirement_text, c.get("code_text", "")[:2000]) for c in candidates]
        try:
            scores = encoder.predict(pairs)
            reranked = []
            for i, c in enumerate(candidates):
                ce_score = float(scores[i])
                normalized = 1 / (1 + 2.718 ** (-ce_score))  # sigmoid
                orig_embed = c.get("embed_score", c.get("score", 0))  # preserve original embedding score
                combined = 0.4 * normalized + 0.6 * c.get("score", 0)
                reranked.append({**c, "score": combined, "embed_score": orig_embed, "ce_score": ce_score})
            reranked.sort(key=lambda x: x["score"], reverse=True)
            return reranked[:top_k]
        except Exception as exc:
            logger.warning("Cross-encoder rerank failed: %s", exc)

    # Fallback to Gemini
    return _gemini_rerank(requirement_text, candidates, top_k)


def is_available() -> bool:
    """Check if any reranker backend is available."""
    if _get_cross_encoder() is not None:
        return True
    _get_gemini_client()
    return _gemini_available is True
