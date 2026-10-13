import pytest

from orbit.semantic.embeddings import (
    EmbeddingError,
    FastEmbedProvider,
    validate_texts,
    validate_vector,
)
from tests.semantic.fakes import FakeProvider


def test_validate_vector_accepts_correct_dimension():
    assert validate_vector([1, 2, 3], 3) == [1.0, 2.0, 3.0]


@pytest.mark.parametrize("vector", [[1, 2], [1, 2, 3, 4], [1, float("nan"), 3], [1, float("inf"), 3]])
def test_validate_vector_rejects_invalid(vector):
    with pytest.raises(EmbeddingError):
        validate_vector(vector, 3)


@pytest.mark.parametrize("bad", ["", "   ", "a\x00b", None, 5])
def test_validate_texts_rejects_invalid_input(bad):
    with pytest.raises(EmbeddingError):
        validate_texts(["fine", bad])


def test_fake_provider_batches_and_is_deterministic():
    provider = FakeProvider()
    first = provider.embed_documents(["local sqlite storage", "hosted cloud"])
    assert first == provider.embed_documents(["local sqlite storage", "hosted cloud"])
    assert len(first) == 2 and len(first[0]) == provider.dimension


def test_fastembed_unsupported_model_is_a_clear_error():
    pytest.importorskip("fastembed")
    with pytest.raises(EmbeddingError, match="unsupported embedding model"):
        FastEmbedProvider("no-such/model-xyz")


def test_section_margin_setting_validation(monkeypatch):
    from orbit.semantic.config import load_settings
    monkeypatch.delenv("CELESTIN_SEMANTIC_SECTION_MARGIN", raising=False)
    assert load_settings().section_margin is None
    monkeypatch.setenv("CELESTIN_SEMANTIC_SECTION_MARGIN", "0.08")
    assert load_settings().section_margin == 0.08
    for bad in ("abc", "-0.1", "1.5"):
        monkeypatch.setenv("CELESTIN_SEMANTIC_SECTION_MARGIN", bad)
        with pytest.raises(ValueError, match="SECTION_MARGIN"):
            load_settings()
