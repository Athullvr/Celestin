"""Retrieval, ranking, and context assembly."""

from .context_builder import (
    DEFAULT_TOKEN_BUDGET,
    ContextBundle,
    ContextItem,
    ExclusionCount,
    ExcludedRecord,
    Utf8ByteTokenEstimator,
    build_context_bundle,
)
from .fts import (
    FtsMessageSearch,
    FtsSchema,
    SearchIndexUnavailable,
    SearchResult,
)
from .ranking import (
    RankingPolicy,
    RetrievalCandidate,
    rank_candidates,
)
from .service import (
    DECISION_FTS_SCHEMA,
    MESSAGE_FTS_SCHEMA,
    RetrievalService,
)

__all__ = [
    "FtsMessageSearch",
    "FtsSchema",
    "SearchIndexUnavailable",
    "SearchResult",
    "RankingPolicy",
    "RetrievalCandidate",
    "rank_candidates",
    "DEFAULT_TOKEN_BUDGET",
    "ContextBundle",
    "ContextItem",
    "ExclusionCount",
    "ExcludedRecord",
    "Utf8ByteTokenEstimator",
    "build_context_bundle",
    "MESSAGE_FTS_SCHEMA",
    "DECISION_FTS_SCHEMA",
    "RetrievalService",
]
