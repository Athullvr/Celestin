"""Optional reranking of a bounded shortlist of heading-section candidates.

A reranker only REORDERS candidates (best first); it never drops one and does not claim a candidate
contains the answer. Rerankers see the current best-first order, the query, each section's heading
path and text. Scores are used for ordering only and are never compared with other retrieval methods.

* ``lexical`` / ``lexical_rrf``: deterministic, no model. BM25-style term statistics over the shortlist
  (heading words count double); ``lexical`` uses that order alone (ties keep the incoming order),
  ``lexical_rrf`` fuses it with the incoming order by Reciprocal Rank Fusion.
* ``cross_encoder`` / ``cross_encoder_rrf``: a small local cross-encoder through fastembed (already an
  optional dependency of the ``semantic`` extra); the first run downloads the model.
"""

from __future__ import annotations

import math
import re
from typing import Protocol, Sequence

from orbit.retrieval.fts import _STOPWORDS, _WORD
from orbit.retrieval.hybrid import RRF_K, reciprocal_rank_fusion
from orbit.retrieval.strategies import Candidate

DEFAULT_CROSS_ENCODER = "Xenova/ms-marco-MiniLM-L-6-v2"
MAX_CROSS_ENCODER_CHARS = 2000
MODES = ("lexical", "lexical_rrf", "cross_encoder", "cross_encoder_rrf")


class RerankUnavailable(RuntimeError):
    """The reranker cannot run now (missing dependency or model); callers keep the original order."""


class SectionReranker(Protocol):
    name: str

    def rerank(self, query: str, candidates: Sequence[Candidate]) -> list[str]:
        """Return the candidates' record ids, best first. ``candidates`` arrive in the current order."""


def _terms(text: str) -> list[str]:
    return [w.casefold() for w in _WORD.findall(text) if w.casefold() not in _STOPWORDS and len(w) > 1]


def _stem(word: str) -> str:
    return re.sub(r"(ing|ed|es|s)$", "", word) if len(word) > 4 else word


def _doc_text(candidate: Candidate) -> str:
    return f"{candidate.source.get('section', '')}\n{candidate.content}"


class LexicalReranker:
    """Deterministic lexical evidence score over the shortlist (optionally fused with the incoming order)."""

    def __init__(self, k1: float = 1.2, b: float = 0.75, *, fuse: bool = False) -> None:
        self.name = "lexical_rrf" if fuse else "lexical"
        self._k1, self._b, self._fuse = k1, b, fuse

    def rerank(self, query: str, candidates: Sequence[Candidate]) -> list[str]:
        ids = [c.record_id for c in candidates]
        query_terms = sorted({_stem(t) for t in _terms(query)})
        if len(candidates) < 2 or not query_terms:
            return ids
        docs = []
        for c in candidates:
            heading = [_stem(t) for t in _terms(str(c.source.get("section", "")))]
            body = [_stem(t) for t in _terms(c.content)]
            docs.append(heading * 2 + body)  # heading words count double
        n = len(docs)
        average = sum(len(d) for d in docs) / n or 1.0
        document_freq = {t: sum(t in set(d) for d in docs) for t in query_terms}
        scores = []
        for d in docs:
            counts = {t: d.count(t) for t in query_terms}
            score = 0.0
            for t in query_terms:
                if not counts[t]:
                    continue
                idf = math.log(1 + (n - document_freq[t] + 0.5) / (document_freq[t] + 0.5))
                score += idf * counts[t] * (self._k1 + 1) / (counts[t] + self._k1 * (1 - self._b + self._b * len(d) / average))
            scores.append(score)
        position = {rid: i for i, rid in enumerate(ids)}
        lexical = sorted(ids, key=lambda rid: (-scores[position[rid]], position[rid]))
        if not self._fuse:
            return lexical
        return [rid for rid, _ in reciprocal_rank_fusion([ids, lexical], RRF_K)]


_cross_encoders: dict[str, object] = {}


class CrossEncoderReranker:
    """Small local cross-encoder (fastembed). ``fuse`` combines its order with the incoming order."""

    def __init__(self, model_id: str = DEFAULT_CROSS_ENCODER, *, fuse: bool = False, cache_dir: str | None = None) -> None:
        self.name = "cross_encoder_rrf" if fuse else "cross_encoder"
        self._model_id = model_id
        self._fuse = fuse
        self._cache_dir = cache_dir
        self.last_scores: dict[str, float] = {}

    def _model(self):
        if self._model_id not in _cross_encoders:
            try:
                from fastembed.rerank.cross_encoder import TextCrossEncoder
            except ImportError as exc:
                raise RerankUnavailable("fastembed is not installed; run: pip install 'celestin-memory[semantic]'") from exc
            try:
                _cross_encoders[self._model_id] = TextCrossEncoder(self._model_id, cache_dir=self._cache_dir)
            except Exception as exc:
                raise RerankUnavailable(
                    f"could not load cross-encoder {self._model_id!r} (first use needs a download): {type(exc).__name__}"
                ) from exc
        return _cross_encoders[self._model_id]

    def rerank(self, query: str, candidates: Sequence[Candidate]) -> list[str]:
        ids = [c.record_id for c in candidates]
        if len(candidates) < 2 or not query.strip():
            return ids
        model = self._model()
        try:
            raw = list(model.rerank(query, [_doc_text(c)[:MAX_CROSS_ENCODER_CHARS] for c in candidates]))
        except Exception as exc:
            raise RerankUnavailable(f"cross-encoder inference failed: {type(exc).__name__}") from exc
        if len(raw) != len(ids) or any(not math.isfinite(float(s)) for s in raw):
            raise RerankUnavailable("cross-encoder returned invalid scores")
        self.last_scores = {rid: float(s) for rid, s in zip(ids, raw)}
        ordered = [rid for rid, _ in sorted(zip(ids, raw), key=lambda p: (-float(p[1]), p[0]))]
        if not self._fuse:
            return ordered
        return [rid for rid, _ in reciprocal_rank_fusion([ids, ordered], RRF_K)]


def build_reranker(mode: str | None, *, model_id: str | None = None) -> SectionReranker | None:
    """Reranker for a mode name, or None when unset. Unknown names raise ValueError."""
    if not mode:
        return None
    if mode in ("lexical", "lexical_rrf"):
        return LexicalReranker(fuse=mode.endswith("_rrf"))
    if mode in ("cross_encoder", "cross_encoder_rrf"):
        return CrossEncoderReranker(model_id or DEFAULT_CROSS_ENCODER, fuse=mode.endswith("_rrf"))
    raise ValueError(f"unknown section reranker {mode!r}; choose from {', '.join(MODES)}")
