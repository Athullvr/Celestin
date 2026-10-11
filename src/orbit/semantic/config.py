"""Opt-in semantic search configuration and wiring.

Semantic search is disabled unless ``CELESTIN_SEMANTIC_SEARCH`` is set to
``1``/``true``/``yes``/``on``. Embedding model files are downloaded on first
use, so enabling it is an explicit choice. When disabled, Celestin behaves
exactly as the FTS5-only server.

Environment variables:
    CELESTIN_SEMANTIC_SEARCH          enable hybrid retrieval and indexing
    CELESTIN_EMBEDDING_MODEL          fastembed model id (default BAAI/bge-small-en-v1.5)
    CELESTIN_EMBEDDING_CACHE_DIR      model cache directory (fastembed default if unset)
    CELESTIN_VECTOR_DB_PATH           vector index file (default: <database path>.vectors.db)
    CELESTIN_SEMANTIC_MIN_SIMILARITY  cosine similarity cut-off, 0..1 (default 0.5)
"""

from __future__ import annotations

import logging
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from orbit.database import engine

from .embeddings import DEFAULT_MODEL_ID, EmbeddingError, EmbeddingProvider, FastEmbedProvider
from .indexer import Indexer
from .search import SemanticSearch
from .vector_index import VectorIndex

logger = logging.getLogger(__name__)

DEFAULT_MIN_SIMILARITY = 0.5
_TRUE = {"1", "true", "yes", "on"}
_providers: dict[tuple[str, str | None], EmbeddingProvider] = {}


@dataclass(frozen=True)
class SemanticSettings:
    enabled: bool
    model_id: str
    cache_dir: str | None
    vector_path: Path
    min_similarity: float


def load_settings(db_path: str | Path | None = None) -> SemanticSettings:
    env = os.environ
    database = engine._resolve_path(db_path)
    raw = env.get("CELESTIN_SEMANTIC_MIN_SIMILARITY")
    try:
        min_similarity = float(raw) if raw else DEFAULT_MIN_SIMILARITY
    except ValueError:
        raise ValueError("CELESTIN_SEMANTIC_MIN_SIMILARITY must be a number") from None
    if not 0.0 <= min_similarity <= 1.0:
        raise ValueError("CELESTIN_SEMANTIC_MIN_SIMILARITY must be between 0 and 1")
    return SemanticSettings(
        enabled=env.get("CELESTIN_SEMANTIC_SEARCH", "").strip().lower() in _TRUE,
        model_id=env.get("CELESTIN_EMBEDDING_MODEL") or DEFAULT_MODEL_ID,
        cache_dir=env.get("CELESTIN_EMBEDDING_CACHE_DIR") or None,
        vector_path=Path(env.get("CELESTIN_VECTOR_DB_PATH") or f"{database}.vectors.db"),
        min_similarity=min_similarity,
    )


def get_provider(settings: SemanticSettings) -> EmbeddingProvider:
    """Process-wide provider so the model loads once per server process."""
    key = (settings.model_id, settings.cache_dir)
    if key not in _providers:
        _providers[key] = FastEmbedProvider(settings.model_id, cache_dir=settings.cache_dir)
    return _providers[key]


def build_semantic_search(db_path: str | Path | None = None) -> SemanticSearch | None:
    """Return a SemanticSearch when enabled, else None. Never raises for provider setup:
    a failure is returned as a search object that reports itself unavailable."""
    settings = load_settings(db_path)
    if not settings.enabled:
        return None
    try:
        provider = get_provider(settings)
    except EmbeddingError as exc:
        return SemanticSearch.unavailable(str(exc))
    return SemanticSearch(provider, settings.vector_path, settings.min_similarity)


def index_after_write(
    connection: sqlite3.Connection, kind: str, record_id: int, db_path: str | Path | None = None
) -> None:
    """Best-effort incremental indexing after a SQLite write.

    SQLite is already committed; a failure here is logged and left for
    ``celestin-index sync`` to repair. It never fails the caller's write.
    """
    try:
        settings = load_settings(db_path)
        if not settings.enabled:
            return
        provider = get_provider(settings)
        with VectorIndex(
            settings.vector_path, model_id=provider.model_id, dimension=provider.dimension
        ) as index:
            Indexer(connection, provider, index).index_record(kind, record_id)
    except Exception as exc:
        logger.warning(
            "semantic indexing of %s %s deferred (%s); run `celestin-index sync`",
            kind, record_id, type(exc).__name__,
        )
