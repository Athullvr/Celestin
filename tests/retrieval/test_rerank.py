"""Section reranking (experimental, off by default): reorders a bounded shortlist, never drops."""

import sys

import pytest

from orbit.retrieval.rerank import (
    CrossEncoderReranker, LexicalReranker, RerankUnavailable, build_reranker, _cross_encoders,
)
from orbit.retrieval.strategies import Candidate


def cand(rid, section, content, score=None):
    return Candidate(rid, "document_section", "p", content, None, "d.md", "sections_semantic", 1, score,
                     source={"section": section})


A = cand("doc:d.md#0001", "Guide > Intro", "welcome to the project, nothing technical here", 0.70)
B = cand("doc:d.md#0002", "Guide > Embedding model decision", "the default embedding model download is about 130 MB", 0.65)
C = cand("doc:d.md#0003", "Guide > Cooking", "pasta and tomato recipe", 0.64)
Q = "how big is the default embedding model download"


# ---- lexical reranker -------------------------------------------------------

def test_lexical_reranker_promotes_the_section_that_shares_the_terms():
    order = LexicalReranker().rerank(Q, [A, C, B])  # incoming order puts the answer last
    assert order[0] == B.record_id and sorted(order) == sorted([A.record_id, B.record_id, C.record_id])


def test_lexical_rrf_blends_instead_of_replacing_the_incoming_order():
    blended = LexicalReranker(fuse=True).rerank(Q, [A, C, B])
    assert sorted(blended) == sorted([A.record_id, B.record_id, C.record_id])
    assert blended == LexicalReranker(fuse=True).rerank(Q, [A, C, B])


def test_lexical_reranker_is_deterministic_and_stable_on_ties():
    first = LexicalReranker().rerank(Q, [A, C, B])
    assert first == LexicalReranker().rerank(Q, [A, C, B])
    tie1 = cand("doc:x#2", "X", "same words here")
    tie2 = cand("doc:x#1", "X", "same words here")
    assert LexicalReranker().rerank("unrelated query terms", [tie1, tie2]) == [tie1.record_id, tie2.record_id]  # incoming order


@pytest.mark.parametrize("candidates", [[], [A]])
def test_lexical_reranker_handles_empty_and_single_candidates(candidates):
    assert LexicalReranker().rerank(Q, candidates) == [c.record_id for c in candidates]


def test_lexical_reranker_without_usable_query_terms_keeps_the_order():
    assert LexicalReranker().rerank("the of and", [C, B, A]) == [C.record_id, B.record_id, A.record_id]
    assert LexicalReranker().rerank("", [C, B]) == [C.record_id, B.record_id]


def test_missing_scores_do_not_matter_to_the_lexical_reranker():
    no_score = [cand("doc:d.md#9", "Embedding", "embedding model download size", None), A]
    assert LexicalReranker().rerank(Q, no_score)[0] == "doc:d.md#9"


# ---- cross-encoder reranker (fake model; no download) -------------------------

class FakeModel:
    def __init__(self, scores=None, fail=False):
        self.scores, self.fail, self.seen = scores, fail, []

    def rerank(self, query, documents):
        self.seen.append((query, list(documents)))
        if self.fail:
            raise RuntimeError("boom")
        return self.scores if self.scores is not None else [float(len(d)) for d in documents]


@pytest.fixture()
def fake_ce(monkeypatch):
    monkeypatch.setitem(_cross_encoders, "fake-model", FakeModel([0.1, 5.0, -3.0]))
    yield _cross_encoders["fake-model"]
    _cross_encoders.pop("fake-model", None)


def test_cross_encoder_orders_by_model_score_and_sends_path_plus_text(fake_ce):
    order = CrossEncoderReranker("fake-model").rerank(Q, [A, B, C])
    assert order == [B.record_id, A.record_id, C.record_id]
    assert "Embedding model decision" in fake_ce.seen[0][1][1] and "130 MB" in fake_ce.seen[0][1][1]


def test_cross_encoder_rrf_mode_blends_with_the_incoming_order(fake_ce):
    blended = CrossEncoderReranker("fake-model", fuse=True).rerank(Q, [A, B, C])
    assert blended[-1] == C.record_id and set(blended[:2]) == {A.record_id, B.record_id}


def test_cross_encoder_ties_are_deterministic(monkeypatch):
    monkeypatch.setitem(_cross_encoders, "tie", FakeModel([1.0, 1.0, 1.0]))
    assert CrossEncoderReranker("tie").rerank(Q, [C, A, B]) == sorted(c.record_id for c in (A, B, C))


@pytest.mark.parametrize("model", [FakeModel(fail=True), FakeModel([1.0]), FakeModel([1.0, float("nan"), 2.0])])
def test_cross_encoder_failures_become_rerank_unavailable(monkeypatch, model):
    monkeypatch.setitem(_cross_encoders, "bad", model)
    with pytest.raises(RerankUnavailable):
        CrossEncoderReranker("bad").rerank(Q, [A, B, C])


def test_cross_encoder_without_fastembed_is_unavailable(monkeypatch):
    monkeypatch.delitem(_cross_encoders, "absent-model", raising=False)
    monkeypatch.setitem(sys.modules, "fastembed", None)
    monkeypatch.setitem(sys.modules, "fastembed.rerank.cross_encoder", None)
    with pytest.raises(RerankUnavailable, match="fastembed"):
        CrossEncoderReranker("absent-model").rerank(Q, [A, B])


def test_build_reranker():
    assert build_reranker(None) is None and build_reranker("") is None
    assert build_reranker("lexical").name == "lexical" and build_reranker("lexical_rrf").name == "lexical_rrf"
    assert build_reranker("cross_encoder").name == "cross_encoder"
    assert build_reranker("cross_encoder_rrf").name == "cross_encoder_rrf"
    with pytest.raises(ValueError, match="unknown section reranker"):
        build_reranker("magic")
