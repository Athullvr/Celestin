"""Local Julia-1 adapter contracts; the unit tests use a fake engine and no model download."""

import sys

import pytest

from orbit.retrieval.rerank import RerankUnavailable
from orbit.retrieval.strategies import Candidate
from orbit.retrieval.system1 import Julia1Reranker, MAX_CHOICES, MAX_OPTION_TOKENS, build_julia1_reranker


def candidate(record_id="m1", text="useful memory", *, record_type="chat_message", project="p", status=None):
    return Candidate(record_id, record_type, project, text, None, None, "fts", 1, 0.0, status=status)


class Tokenizer:
    mask_token = "<MASK>"

    def __call__(self, text, add_special_tokens=False):
        return {"input_ids": text.split()}

    def decode(self, tokens, skip_special_tokens=True):
        return " ".join(tokens)


class Engine:
    tokenizer = Tokenizer()

    def __init__(self, probabilities):
        self.probabilities = probabilities
        self.request = None

    def predict(self, **kwargs):
        self.request = kwargs
        return {"answers": {"relevance": {"probabilities": self.probabilities}}}


def test_adapter_maps_choice_probabilities_to_stable_candidate_order():
    engine = Engine({"candidate_00": 0.1, "candidate_01": 0.7, "candidate_02": 0.2})
    reranker = Julia1Reranker(None, engine=engine)
    items = [candidate("a"), candidate("b"), candidate("c")]
    assert reranker.rerank("query", items) == ["b", "c", "a"]
    assert list(engine.request["questions"]["relevance"]["criteria"]) == [
        "candidate_00", "candidate_01", "candidate_02"
    ]


def test_adapter_keeps_input_order_for_probability_ties():
    engine = Engine({"candidate_00": 0.5, "candidate_01": 0.5})
    assert Julia1Reranker(None, engine=engine).rerank("query", [candidate("z"), candidate("a")]) == ["z", "a"]


@pytest.mark.parametrize("probabilities", [
    {"candidate_00": 0.5},
    {"candidate_00": 0.8, "candidate_01": 0.8},
    {"candidate_00": float("nan"), "candidate_01": 0.0},
])
def test_adapter_rejects_malformed_or_unnormalized_model_output(probabilities):
    reranker = Julia1Reranker(None, engine=Engine(probabilities))
    with pytest.raises(RerankUnavailable, match="inference failed"):
        reranker.rerank("query", [candidate("a"), candidate("b")])


def test_candidate_text_is_clipped_to_model_choice_token_limit_and_mask_is_removed():
    engine = Engine({"candidate_00": 1.0, "candidate_01": 0.0})
    long = candidate("a", " ".join(["word"] * (MAX_OPTION_TOKENS + 10) + ["<MASK>"]))
    Julia1Reranker(None, engine=engine).rerank("query", [long, candidate("b")])
    option = engine.request["questions"]["relevance"]["criteria"]["candidate_00"]
    assert len(option.split()) <= MAX_OPTION_TOKENS
    assert "<MASK>" not in option


def test_twenty_choice_shortlist_uses_a_shared_strict_head_budget():
    probabilities = {f"candidate_{i:02d}": 1 / MAX_CHOICES for i in range(MAX_CHOICES)}
    engine = Engine(probabilities)
    items = [candidate(str(i), " ".join([f"word{i}"] * 50)) for i in range(MAX_CHOICES)]
    Julia1Reranker(None, engine=engine).rerank("query", items)
    options = engine.request["questions"]["relevance"]["criteria"].values()
    assert all(len(option.split()) <= 24 for option in options)


@pytest.mark.parametrize("items", [[], [candidate()]])
def test_small_shortlists_bypass_the_model(items):
    reranker = Julia1Reranker(None)
    with pytest.raises(RerankUnavailable, match="between 2 and 20"):
        reranker.rerank("query", items)


def test_shortlist_above_model_limit_is_rejected():
    reranker = Julia1Reranker(None)
    items = [candidate(str(i)) for i in range(MAX_CHOICES + 1)]
    with pytest.raises(RerankUnavailable, match="between 2 and 20"):
        reranker.rerank("query", items)


def test_duplicate_candidate_ids_are_rejected():
    reranker = Julia1Reranker(None, engine=Engine({}))
    with pytest.raises(RerankUnavailable, match="unique"):
        reranker.rerank("query", [candidate("same"), candidate("same")])


def test_missing_model_path_is_content_free_and_cached():
    reranker = Julia1Reranker(None)
    expected = ("requires Python" if not (3, 11) <= sys.version_info[:2] < (3, 14)
                else "set CELESTIN_SYSTEM1_MODEL_PATH")
    for _ in range(2):
        with pytest.raises(RerankUnavailable, match=expected) as error:
            reranker.health_check()
        assert "baseline ranking retained" in str(error.value)


def test_reranker_factory_reuses_one_lazy_adapter():
    build_julia1_reranker.cache_clear()
    first = build_julia1_reranker("/tmp/not-loaded")
    assert first is build_julia1_reranker("/tmp/not-loaded")


def test_product_system1_switch_is_opt_in_and_invalid_values_fail_to_baseline(monkeypatch):
    from orbit.mcp_server import retrieval_services
    from orbit.retrieval.service import LayaCandidateReranker

    monkeypatch.delenv("CELESTIN_RETRIEVAL_PATH", raising=False)
    monkeypatch.setenv("CELESTIN_SYSTEM1_MODEL_PATH", "/local/model")
    assert retrieval_services._system1_from_env() is None
    monkeypatch.setenv("CELESTIN_RETRIEVAL_PATH", "typo")
    assert retrieval_services._system1_from_env() is None

    marker = LayaCandidateReranker(agent=object())
    monkeypatch.setenv("CELESTIN_RETRIEVAL_PATH", "system1")
    monkeypatch.setattr(retrieval_services, "build_laya_reranker", lambda: marker)
    assert retrieval_services._system1_from_env() is marker

    monkeypatch.setenv("CELESTIN_RETRIEVAL_PATH", "julia1")
    monkeypatch.setattr(retrieval_services, "build_julia1_reranker", lambda path: (path, marker))
    assert retrieval_services._system1_from_env() == ("/local/model", marker)


def test_system1_opt_in_does_not_change_mcp_public_response_keys(tmp_path, monkeypatch):
    from orbit.database.engine import connect
    from orbit.mcp_server import retrieval_services
    from orbit.repositories.messages import ChatMessageRepository

    db_path = tmp_path / "messages.db"
    with connect(db_path) as connection:
        messages = ChatMessageRepository(connection)
        for i in range(3):
            messages.insert("p", "c", "user", f"reference note number {i}")

    class Reverse:
        name = "julia-1"

        def rerank(self, query, candidates):
            return [c.record_id for c in reversed(list(candidates))]

    monkeypatch.setenv("CELESTIN_RETRIEVAL_PATH", "baseline")
    baseline = retrieval_services.RetrievalServices(db_path).retrieve_context("p", "reference", 1000)
    monkeypatch.setattr(retrieval_services, "_system1_from_env", lambda: Reverse())
    system1 = retrieval_services.RetrievalServices(db_path).retrieve_context("p", "reference", 1000)
    assert system1.keys() == baseline.keys()
    assert {item["record_id"] for item in system1["items"]} == {item["record_id"] for item in baseline["items"]}
