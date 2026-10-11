"""Embedding provider interface and the default local provider.

The default provider runs a local ONNX model through ``fastembed``. Text never
leaves the machine except for the one-time model download from Hugging Face.
"""

from __future__ import annotations

import math
from typing import Protocol, Sequence

DEFAULT_MODEL_ID = "BAAI/bge-small-en-v1.5"
DEFAULT_BATCH_SIZE = 32


class EmbeddingError(RuntimeError):
    """Embeddings could not be produced (missing dependency, model, or bad output)."""


class EmbeddingProvider(Protocol):
    """Replaceable text-to-vector backend."""

    model_id: str
    dimension: int

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed texts in order; must return exactly one vector per text."""

    def embed_query(self, text: str) -> list[float]:
        """Embed one search query."""


def validate_vector(vector: Sequence[float], dimension: int) -> list[float]:
    """Return ``vector`` as floats, rejecting wrong sizes and non-finite values."""
    values = [float(x) for x in vector]
    if len(values) != dimension:
        raise EmbeddingError(f"expected a {dimension}-dimensional vector, got {len(values)}")
    if not all(math.isfinite(x) for x in values):
        raise EmbeddingError("vector contains NaN or infinite values")
    return values


def validate_texts(texts: Sequence[str]) -> list[str]:
    cleaned = []
    for text in texts:
        if not isinstance(text, str) or not text.strip() or "\x00" in text:
            raise EmbeddingError("embedding input must be non-empty text without NUL characters")
        cleaned.append(text)
    return cleaned


class FastEmbedProvider:
    """Local embeddings via fastembed (ONNX Runtime; no PyTorch)."""

    def __init__(
        self,
        model_id: str = DEFAULT_MODEL_ID,
        *,
        cache_dir: str | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise EmbeddingError(
                "fastembed is not installed; run: pip install 'celestin-memory[semantic]'"
            ) from exc
        self._text_embedding = TextEmbedding
        self.model_id = model_id
        self._cache_dir = cache_dir
        self._batch_size = batch_size
        self._model = None
        try:
            self.dimension = int(TextEmbedding.get_embedding_size(model_id))
        except Exception as exc:
            raise EmbeddingError(f"unsupported embedding model {model_id!r}") from exc

    def _load(self):
        if self._model is None:
            try:
                self._model = self._text_embedding(self.model_id, cache_dir=self._cache_dir)
            except Exception as exc:
                raise EmbeddingError(
                    f"could not load embedding model {self.model_id!r} "
                    f"(first use needs a network download): {type(exc).__name__}"
                ) from exc
        return self._model

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        texts = validate_texts(texts)
        if not texts:
            return []
        try:
            vectors = [v.tolist() for v in self._load().embed(texts, batch_size=self._batch_size)]
        except EmbeddingError:
            raise
        except Exception as exc:
            raise EmbeddingError(f"embedding failed: {type(exc).__name__}") from exc
        if len(vectors) != len(texts):
            raise EmbeddingError("embedding provider returned the wrong number of vectors")
        return [validate_vector(v, self.dimension) for v in vectors]

    def embed_query(self, text: str) -> list[float]:
        (text,) = validate_texts([text])
        try:
            vector = next(iter(self._load().query_embed(text))).tolist()
        except EmbeddingError:
            raise
        except Exception as exc:
            raise EmbeddingError(f"query embedding failed: {type(exc).__name__}") from exc
        return validate_vector(vector, self.dimension)
