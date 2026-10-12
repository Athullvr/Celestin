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
        min_similarity: float = 0.6,
        *,
        relative_margin: float | None = None,
        unavailable_reason: str | None = None,
    ) -> None:
        self._provider = provider
        self._path = Path(vector_path)
        self._min_similarity = min_similarity
        self._margin = relative_margin
        self._reason = unavailable_reason

    @classmethod
    def unavailable(cls, reason: str) -> "SemanticSearch":
        return cls(None, "", unavailable_reason=reason)

    def search(
        self, project: str, query: str, *, kinds: tuple[str, ...], limit: int
    ) -> dict[str, list[VectorHit]]:
        """Return hits per kind with similarity >= the configured minimum.

        With ``relative_margin`` set, hits more than that far below the best hit of
        their kind are also dropped, so weak neighbours do not fill the context.

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
                    kind: self._select(index.search(vector, project=project, kind=kind, limit=limit))
                    for kind in kinds
                }
        except (EmbeddingError, VectorIndexError) as exc:
            raise SemanticUnavailable(str(exc)) from exc

    def _select(self, hits: list[VectorHit]) -> list[VectorHit]:
        hits = [h for h in hits if h.similarity >= self._min_similarity]
        if self._margin is not None and hits:
            best = max(h.similarity for h in hits)
            hits = [h for h in hits if h.similarity >= best - self._margin]
        return hits
