"""Deterministic fake embeddings for unit tests ONLY.

Words map to a few hand-written concept dimensions. This is not semantic
search; it just gives tests controllable vector geometry.
"""

from __future__ import annotations

import re

from orbit.semantic.embeddings import EmbeddingError

CONCEPTS = [
    {"persistence", "sqlite", "storage", "database", "local"},
    {"hosted", "deployment", "infrastructure", "server", "cloud", "overhead"},
    {"cooking", "pasta", "tomato", "recipe"},
    {"auth", "login", "password", "token"},
]


def _vector(text: str) -> list[float]:
    words = set(re.findall(r"[a-z]+", text.lower()))
    vec = [float(len(words & concept)) for concept in CONCEPTS]
    return vec + [0.01]  # never an all-zero vector


class FakeProvider:
    model_id = "fake-concepts-v1"
    dimension = len(CONCEPTS) + 1

    def __init__(self) -> None:
        self.fail = False
        self.document_calls: list[list[str]] = []

    def _check(self) -> None:
        if self.fail:
            raise EmbeddingError("fake provider outage")

    def embed_documents(self, texts):
        self._check()
        self.document_calls.append(list(texts))
        return [_vector(t) for t in texts]

    def embed_query(self, text):
        self._check()
        return _vector(text)
