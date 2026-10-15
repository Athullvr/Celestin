"""Local Laya candidate selection stays inside the existing retrieval service."""

import json
import time

import pytest

from orbit.retrieval.service import LayaCandidateReranker, RetrievalService
from orbit.retrieval.strategies import Candidate, RetrievalRequest


class FakeTokenizer:
    def __call__(self, state, **kwargs):
        if '"candidate_text":"oversize"' in state:
            return {"input_ids": list(range(2049))}
        return {"input_ids": state.split()}


class FakeAgent:
    tok = FakeTokenizer()

    def __init__(self):
        self.requests = None

    def predict_batch(self, states, questions, **kwargs):
        self.requests = [{"state": state, "questions": questions, **kwargs} for state in states]
        results = []
        for state in states:
            payload = json.loads(state)
            if payload["candidate_text"] == "best evidence":
                probabilities = {"direct": 0.9, "supporting": 0.05, "related": 0.03, "irrelevant": 0.02}
            else:
                probabilities = {"direct": 0.05, "supporting": 0.05, "related": 0.1, "irrelevant": 0.8}
            results.append({"answers": {"relevance": {"probabilities": probabilities}}})
        return results


class BrokenAgent(FakeAgent):
    def predict_batch(self, states, questions, **kwargs):
        raise RuntimeError("must not log candidate content")


class SlowAgent(FakeAgent):
    def predict_batch(self, states, questions, **kwargs):
        time.sleep(0.1)
        return super().predict_batch(states, questions, **kwargs)


class MalformedAgent(FakeAgent):
    def predict_batch(self, states, questions, **kwargs):
        self.requests = [{"state": state, "questions": questions, **kwargs} for state in states]
        return [{"answers": {"relevance": {"probabilities": {"direct": float("nan")}}}}
                for _ in states]


class TruncatedAgent(FakeAgent):
    def predict_batch(self, states, questions, **kwargs):
        self.requests = [{"state": state, "questions": questions, **kwargs} for state in states]
        return [{"usage": {"state_tokens_dropped": 1},
                 "answers": {"relevance": {"probabilities": {
                     "direct": 0.25, "supporting": 0.25, "related": 0.25, "irrelevant": 0.25,
                 }}}} for _ in states]


class RoundedAgent(FakeAgent):
    def predict_batch(self, states, questions, **kwargs):
        results = super().predict_batch(states, questions, **kwargs)
        for result in results:
            result["answers"]["relevance"]["probabilities"]["irrelevant"] -= 0.0001
        return results


def _candidates(texts):
    return {
        key: Candidate(key, "chat_message", "p", text, None, key, "fts", rank, -float(rank))
        for rank, (key, text) in enumerate(texts, start=1)
    }


def _run(agent, candidates, *, timeout=1.0, lists=None):
    service = RetrievalService.__new__(RetrievalService)
    service._system1_reranker = LayaCandidateReranker(agent=agent, timeout_seconds=timeout)
    service._rerank_shortlist = 20
    service._system1_warnings = []
    service._system1_trace = {}
    service._rerank_trace = {}
    baseline = {key: float(rank) for rank, key in enumerate(candidates, start=1)}
    request = RetrievalRequest("p", "what is the answer?", 20, 2000)
    after = service._rerank_system1("chat_message", request, candidates, baseline, lists or {})
    return service, baseline, after


def test_laya_uses_batch_payload_with_complete_text_and_engine_evidence():
    agent = FakeAgent()
    candidates = _candidates([("a", "ordinary note"), ("b", "ordinary note two"), ("c", "best evidence")])
    hits = [
        Candidate("a", "chat_message", "p", "ordinary note", None, "a", "fts", 1, -0.2),
        Candidate("b", "chat_message", "p", "ordinary note two", None, "b", "semantic", 2, 0.82),
        Candidate("c", "chat_message", "p", "best evidence", None, "c", "semantic", 3, 0.79),
    ]
    lists = {("chat_message", "fts"): [hits[0]], ("chat_message", "semantic"): hits[1:]}
    service, baseline, updated = _run(agent, candidates, lists=lists)

    assert len(agent.requests) == 3
    first = json.loads(agent.requests[0]["state"])
    assert first["query"] == "what is the answer?"
    assert first["candidate_text"] == "ordinary note"
    assert first["retrieval_evidence"] == [{"method": "fts", "rank": 1, "score": -0.2}]
    assert agent.requests[0]["max_len"] == 2305
    assert agent.requests[0]["head_max_len"] == 256
    assert set(agent.requests[0]["questions"]["relevance"]["criteria"]) == {
        "direct", "supporting", "related", "irrelevant"
    }
    assert sorted(updated, key=updated.get) == ["a", "c", "b"]
    assert service._system1_trace["chat_message"]["failures"] == 0


def test_strong_exact_fts_candidate_keeps_priority_and_original_score_values():
    candidates = _candidates([("a", "ordinary note"), ("b", "ordinary note two"), ("c", "best evidence")])
    exact_hit = Candidate("c", "chat_message", "p", "best evidence", None, "c", "fts", 1, -0.01,
                          tier="strict")
    lists = {("chat_message", "fts"): [exact_hit]}
    service, baseline, updated = _run(FakeAgent(), candidates, lists=lists)

    assert sorted(updated, key=updated.get)[0] == "c"
    assert sorted(updated.values()) == pytest.approx(sorted(baseline.values()))
    payload = json.loads(service._system1_reranker._agent.requests[2]["state"])
    assert payload["retrieval_evidence"] == [{"method": "fts", "rank": 1, "score": -0.01}]


def test_oversized_group_preserves_baseline_and_logs_content_free_skip():
    candidates = _candidates([("a", "ordinary note"), ("b", "oversize")])
    service, baseline, updated = _run(FakeAgent(), candidates)

    assert updated == baseline
    assert service._system1_trace["chat_message"]["input_skips"] == 1
    assert "input_over_budget" in service._system1_warnings[0]
    assert "oversize" not in service._system1_warnings[0]


def test_model_error_and_timeout_keep_baseline_order_with_safe_diagnostics():
    candidates = _candidates([("a", "ordinary note"), ("b", "best evidence")])
    for agent, timeout in ((BrokenAgent(), 1.0), (SlowAgent(), 0.01)):
        service, baseline, updated = _run(agent, candidates, timeout=timeout)
        assert updated == baseline
        warning = " ".join(service._system1_warnings)
        assert "baseline order retained" in warning
        assert "candidate content" not in warning and "best evidence" not in warning


def test_timed_out_inference_does_not_queue_followup_requests():
    candidates = _candidates([("a", "ordinary note"), ("b", "best evidence")])
    started = time.monotonic()
    service, baseline, updated = _run(SlowAgent(), candidates, timeout=0.01)
    assert updated == baseline

    service, baseline, updated = _run(FakeAgent(), candidates, timeout=1.0)
    assert updated == baseline
    assert time.monotonic() - started < 0.08
    assert service._system1_trace["chat_message"]["failures"] == 1

    time.sleep(0.25)
    recovered_agent = FakeAgent()
    service, baseline, updated = _run(recovered_agent, candidates, timeout=1.0)
    assert service._system1_trace["chat_message"]["failures"] == 0
    assert len(recovered_agent.requests) == 2


def test_malformed_or_truncated_model_outputs_keep_baseline_order():
    candidates = _candidates([("a", "ordinary note"), ("b", "best evidence")])
    service, baseline, updated = _run(MalformedAgent(), candidates)
    assert updated == baseline
    assert service._system1_trace["chat_message"]["failures"] == 1

    service, baseline, updated = _run(TruncatedAgent(), candidates)
    assert updated == baseline
    assert service._system1_trace["chat_message"]["input_skips"] == 1


def test_rounded_laya_probabilities_are_accepted():
    candidates = _candidates([("a", "ordinary note"), ("b", "best evidence")])
    service, _, _ = _run(RoundedAgent(), candidates)
    assert service._system1_trace["chat_message"]["failures"] == 0


def test_real_service_laya_keeps_sqlite_rows_and_returns_traceable_scoped_context(tmp_path):
    from orbit.database.engine import connect
    from orbit.repositories.messages import ChatMessageRepository

    connection = connect(tmp_path / "laya-e2e.db")
    repository = ChatMessageRepository(connection)
    source_id = repository.insert("p", "conversation", "assistant", "special answer evidence")
    repository.insert("p", "conversation", "user", "special unrelated note")
    repository.insert("other", "other-conversation", "user", "special foreign evidence")
    before = connection.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0]
    agent = FakeAgent()
    service = RetrievalService(connection, system1_reranker=LayaCandidateReranker(agent=agent))

    bundle = service.retrieve_context("p", "special", 2_000)

    assert bundle.token_count <= bundle.token_budget == 2_000
    assert all(item.project_id == "p" for item in bundle.items)
    assert any(item.source_id == str(source_id) for item in bundle.items)
    assert all("foreign evidence" not in item.content for item in bundle.items)
    states = [json.loads(request["state"]) for request in agent.requests]
    assert states and all("foreign evidence" not in state["candidate_text"] for state in states)
    assert connection.execute("SELECT COUNT(*) FROM chat_messages").fetchone()[0] == before
    assert service.last_diagnostics["rerank"]["reranker"] == "laya-multilingual"
    connection.close()
