"""Embedding module with multiple backends.

Primary: Local sentence-transformers (BAAI/bge-base-en-v1.5, 768d)
Backup:  HuggingFace Inference API, Gemini API
Fallback: Deterministic hash (offline, low quality)

Set TRACEAI_EMBEDDING_PROVIDER in .env:
  local       — sentence-transformers on device (default)
  huggingface — HF Inference API (needs HF_TOKEN)
  gemini      — Google Gemini API (needs GEMINI_API_KEY)
  hash        — deterministic hash (no network)
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import re
import sys
import time
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------

_provider: Optional[str] = None


def _get_provider() -> str:
    global _provider
    if _provider is not None:
        return _provider
    choice = os.environ.get("TRACEAI_EMBEDDING_PROVIDER", "local").lower().strip()
    if choice == "local":
        _provider = "local"
    elif choice in ("huggingface", "hf"):
        _provider = "huggingface"
    elif choice == "gemini":
        _provider = "gemini"
    else:
        _provider = "hash"
    logger.info("Embedding provider: %s", _provider)
    return _provider


# ---------------------------------------------------------------------------
# Local sentence-transformers (primary)
# ---------------------------------------------------------------------------

_local_model = None
_LOCAL_MODEL_NAME = os.environ.get("TRACEAI_LOCAL_MODEL", "BAAI/bge-base-en-v1.5")


def _get_local_model():
    global _local_model
    if _local_model is not None:
        return _local_model
    try:
        from sentence_transformers import SentenceTransformer
        logger.info("Loading model: %s ...", _LOCAL_MODEL_NAME)
        try:
            # Try cached model first (no network needed)
            _local_model = SentenceTransformer(_LOCAL_MODEL_NAME, local_files_only=True)
        except Exception:
            # Download if not cached
            _local_model = SentenceTransformer(_LOCAL_MODEL_NAME)
        logger.info("Model loaded: %s", _LOCAL_MODEL_NAME)
        return _local_model
    except Exception as exc:
        logger.warning("Failed to load model: %s — using hash fallback", exc)
        return None


def _local_embed_single(text: str) -> list[float]:
    model = _get_local_model()
    if model is None:
        raise RuntimeError("Local model unavailable")
    return model.encode(text, normalize_embeddings=True).tolist()


def _local_embed_batch(texts: list[str]) -> list[list[float]]:
    model = _get_local_model()
    if model is None:
        raise RuntimeError("Local model unavailable")
    total = len(texts)
    batch_size = 32
    all_embeddings = []
    for i in range(0, total, batch_size):
        chunk = texts[i:i + batch_size]
        embeddings = model.encode(chunk, normalize_embeddings=True, show_progress_bar=False)
        all_embeddings.extend(embeddings.tolist())
        done = min(i + batch_size, total)
        pct = done / total * 100
        filled = int(pct / 5)
        bar = "█" * filled + "░" * (20 - filled)
        sys.stderr.write(f"\r  Embedding: {done}/{total} [{pct:.0f}%] {bar}")
        sys.stderr.flush()
    sys.stderr.write("\n")
    return all_embeddings


# ---------------------------------------------------------------------------
# HuggingFace Inference API (backup)
# ---------------------------------------------------------------------------

_hf_client = None
_HF_MODEL = "BAAI/bge-base-en-v1.5"


def _get_hf_client():
    global _hf_client
    if _hf_client is not None:
        return _hf_client
    try:
        from huggingface_hub import InferenceClient
        token = os.environ.get("HF_TOKEN", None)
        _hf_client = InferenceClient(token=token)
        return _hf_client
    except Exception as exc:
        logger.warning("Failed to init HF client: %s", exc)
        return None


def _hf_embed_single(text: str) -> list[float]:
    client = _get_hf_client()
    if client is None:
        raise RuntimeError("HF client unavailable")
    for attempt in range(_MAX_RETRIES):
        try:
            result = client.feature_extraction(text, model=_HF_MODEL)
            if hasattr(result, "tolist"):
                result = result.tolist()
            return result[0] if isinstance(result[0], list) else list(result)
        except Exception as exc:
            if attempt < _MAX_RETRIES - 1:
                wait = _retry_wait(exc, attempt)
                logger.warning("HF attempt %d/%d failed: %s — retrying in %.1fs", attempt + 1, _MAX_RETRIES, exc, wait)
                time.sleep(wait)
            else:
                raise


def _hf_embed_batch(texts: list[str]) -> list[list[float]]:
    from concurrent.futures import ThreadPoolExecutor, as_completed
    total = len(texts)
    completed = 0
    results = [None] * total

    def _progress():
        nonlocal completed
        completed += 1
        pct = completed / total * 100
        filled = int(pct / 5)
        bar = "█" * filled + "░" * (20 - filled)
        sys.stderr.write(f"\r  Embedding: {completed}/{total} [{pct:.0f}%] {bar}")
        sys.stderr.flush()
        if completed == total:
            sys.stderr.write("\n")

    with ThreadPoolExecutor(max_workers=10) as pool:
        future_to_idx = {pool.submit(_hf_embed_single, t): i for i, t in enumerate(texts)}
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            results[idx] = future.result()
            _progress()
    return results


# ---------------------------------------------------------------------------
# Gemini API (backup)
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
        logger.warning("Failed to init Gemini client: %s", exc)
        _gemini_available = False
        return None


def _gemini_embed_single(text: str, *, model: str, task_type: str, output_dims: int) -> list[float]:
    client = _get_gemini_client()
    if client is None:
        raise RuntimeError("Gemini client unavailable")
    for attempt in range(_MAX_RETRIES):
        try:
            from google.genai import types
            response = client.models.embed_content(
                model=model, contents=text,
                config=types.EmbedContentConfig(task_type=task_type, output_dimensionality=output_dims),
            )
            return list(response.embeddings[0].values)
        except Exception as exc:
            if attempt < _MAX_RETRIES - 1:
                time.sleep(_retry_wait(exc, attempt))
            else:
                raise


def _gemini_embed_batch(texts: list[str], *, model: str, task_type: str, output_dims: int) -> list[list[float]]:
    client = _get_gemini_client()
    if client is None:
        raise RuntimeError("Gemini client unavailable")
    for attempt in range(_MAX_RETRIES):
        try:
            from google.genai import types
            response = client.models.embed_content(
                model=model, contents=texts,
                config=types.EmbedContentConfig(task_type=task_type, output_dimensionality=output_dims),
            )
            return [list(e.values) for e in response.embeddings]
        except Exception as exc:
            if attempt < _MAX_RETRIES - 1:
                time.sleep(_retry_wait(exc, attempt))
            else:
                raise


# ---------------------------------------------------------------------------
# Retry + Hash fallback
# ---------------------------------------------------------------------------

_MAX_RETRIES = 5
_BASE_BACKOFF = 2.0


def _retry_wait(exc: Exception, attempt: int) -> float:
    if "429" in str(exc) or "RESOURCE_EXHAUSTED" in str(exc):
        return max(2.0, min(60.0, 2.0 * (2 ** attempt)))
    return _BASE_BACKOFF * (2 ** attempt)


def _hash_embed(text: str, vector_size: int) -> list[float]:
    tokens = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    if not tokens:
        return [0.0] * vector_size
    vector = [0.0] * vector_size
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        first = int.from_bytes(digest[:8], byteorder="big", signed=False)
        second = int.from_bytes(digest[8:16], byteorder="big", signed=False)
        vector[first % vector_size] += 1.0 if (second % 2 == 0) else -1.0
    norm = math.sqrt(sum(c * c for c in vector))
    return [c / norm for c in vector] if norm else vector


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def embed_text(
    text: str, vector_size: int, *, model: str = "gemini-embedding-001", task_type: str = "RETRIEVAL_DOCUMENT",
) -> list[float]:
    provider = _get_provider()
    try:
        if provider == "local":
            return _local_embed_single(text)
        if provider == "huggingface":
            return _hf_embed_single(text)
        if provider == "gemini":
            return _gemini_embed_single(text, model=model, task_type=task_type, output_dims=vector_size)
    except Exception as exc:
        logger.warning("%s embed failed, falling back to hash: %s", provider, exc)
    return _hash_embed(text, vector_size)


def embed_batch(
    texts: list[str], vector_size: int, *, model: str = "gemini-embedding-001",
    task_type: str = "RETRIEVAL_DOCUMENT", batch_size: int = 100,
) -> list[list[float]]:
    if not texts:
        return []
    provider = _get_provider()
    try:
        if provider == "local":
            return _local_embed_batch(texts)
        if provider == "huggingface":
            return _hf_embed_batch(texts)
        if provider == "gemini":
            results = []
            for i in range(0, len(texts), batch_size):
                results.extend(_gemini_embed_batch(
                    texts[i:i + batch_size], model=model, task_type=task_type, output_dims=vector_size,
                ))
            return results
    except Exception as exc:
        logger.warning("%s batch embed failed, falling back to hash: %s", provider, exc)
    return [_hash_embed(t, vector_size) for t in texts]
