"""Lightweight BM25 index for hybrid retrieval.

Provides keyword-based search alongside semantic search. BM25 catches exact
class/method name matches that embedding models miss in cross-domain
(natural language → code) retrieval.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Optional


def _tokenize(text: str) -> list[str]:
    """Simple tokenizer: lowercase, split on non-alphanumeric, filter short."""
    tokens = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", text.lower())
    # Split camelCase and PascalCase
    expanded = []
    for t in tokens:
        parts = re.sub(r"([a-z])([A-Z])", r"\1 \2", t).lower().split()
        expanded.extend(parts)
    return [t for t in expanded if len(t) > 1]


class BM25Index:
    """BM25 (Okapi) index for code units.

    Usage:
        idx = BM25Index()
        idx.add_document("id1", "public void getPatient() { ... }")
        idx.add_document("id2", "class AuthDAO extends ...")
        results = idx.search("patient authentication", limit=10)
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.docs: dict[str, list[str]] = {}  # id -> tokens
        self.doc_len: dict[str, int] = {}
        self.avg_dl: float = 0.0
        self.df: Counter = Counter()  # document frequency per term
        self.n_docs: int = 0
        self._built = False

    def add_document(self, doc_id: str, text: str) -> None:
        tokens = _tokenize(text)
        self.docs[doc_id] = tokens
        self.doc_len[doc_id] = len(tokens)
        for term in set(tokens):
            self.df[term] += 1
        self.n_docs += 1
        self._built = False

    def build(self) -> None:
        """Finalize index (compute avg doc length)."""
        if self.n_docs > 0:
            self.avg_dl = sum(self.doc_len.values()) / self.n_docs
        self._built = True

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """Search the index. Returns [{id, score}, ...]."""
        if not self._built:
            self.build()
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        scores: dict[str, float] = {}
        for term in query_tokens:
            if term not in self.df:
                continue
            idf = math.log((self.n_docs - self.df[term] + 0.5) / (self.df[term] + 0.5) + 1.0)
            for doc_id, doc_tokens in self.docs.items():
                tf = doc_tokens.count(term)
                if tf == 0:
                    continue
                dl = self.doc_len[doc_id]
                numerator = tf * (self.k1 + 1)
                denominator = tf + self.k1 * (1 - self.b + self.b * dl / max(self.avg_dl, 1))
                scores[doc_id] = scores.get(doc_id, 0.0) + idf * numerator / denominator

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:limit]
        return [{"id": doc_id, "score": score} for doc_id, score in ranked]
