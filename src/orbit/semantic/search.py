"""Query-time semantic search: embed the query, then run a project-filtered KNN."""

from __future__ import annotations

from pathlib import Path

from .embeddings import EmbeddingError, EmbeddingProvider
from .vector_index import VectorHit, VectorIndex, VectorIndexError


class SemanticUnavailable(RuntimeError):
    """Semantic search cannot run right now; callers should fall back to FTS5."""


class SemanticSearch:
    def __init__(
        self,
        provider: EmbeddingProvider | None,
        vector_path: str | Path,
        min_similarity: float = 0.5,
        *,
        unavailable_reason: str | None = None,
    ) -> None:
        self._provider = provider
        self._path = Path(vector_path)
        self._min_similarity = min_similarity
        self._reason = unavailable_reason

    @classmethod
    def unavailable(cls, reason: str) -> "SemanticSearch":
        return cls(None, "", unavailable_reason=reason)

    def search(
        self, project: str, query: str, *, kinds: tuple[str, ...], limit: int
    ) -> dict[str, list[VectorHit]]:
        """Return hits per kind with similarity >= the configured minimum.

        Raises SemanticUnavailable on any provider or index failure; never
        returns made-up results.
        """
        if self._provider is None:
            raise SemanticUnavailable(self._reason or "embedding provider unavailable")
        try:
            vector = self._provider.embed_query(query)
            with VectorIndex(
                self._path,
                model_id=self._provider.model_id,
                dimension=self._provider.dimension,
                create=False,
            ) as index:
                problems = index.health_check()
                if problems:
                    raise SemanticUnavailable(
                        "vector index is inconsistent (" + "; ".join(problems)
                        + "); run: celestin-index rebuild"
                    )
                return {
                    kind: [
                        hit
                        for hit in index.search(vector, project=project, kind=kind, limit=limit)
                        if hit.similarity >= self._min_similarity
                    ]
                    for kind in kinds
                }
        except (EmbeddingError, VectorIndexError) as exc:
            raise SemanticUnavailable(str(exc)) from exc
