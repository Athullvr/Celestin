"""Rank-based fusion of keyword and semantic result lists."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Hashable, Sequence

RRF_K = 60


@dataclass(frozen=True, slots=True)
class RetrievalInfo:
    """How the last retrieval ran.

    mode: ``fts`` (semantic disabled), ``hybrid``, or ``fts_fallback``
    (semantic enabled but unavailable; results are FTS5-only).
    """

    mode: str = "fts"
    warnings: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {"mode": self.mode, "warnings": list(self.warnings)}


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[Hashable]], k: int = RRF_K
) -> list[tuple[Hashable, float]]:
    """Fuse best-first ranked id lists with Reciprocal Rank Fusion.

    score(id) = sum over lists of 1 / (k + rank), rank starting at 1. Raw
    scores from different engines (BM25, cosine) are never compared. Ties are
    broken by ascending id (ids in one call must be mutually comparable) so the order is deterministic. An id repeated
    inside one list counts only at its best rank.
    """
    scores: dict[Hashable, float] = {}
    for ranking in rankings:
        seen: set[Hashable] = set()
        for rank, item in enumerate(ranking, start=1):
            if item in seen:
                continue
            seen.add(item)
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))
