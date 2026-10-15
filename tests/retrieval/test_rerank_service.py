"""Reranking inside RetrievalService: policy, safety and degradation."""

import pytest

pytest.importorskip("pageindex")

from orbit.database.engine import connect
from orbit.pageindex.indexer import index_markdown_text
from orbit.pageindex.store import PageIndexStore
from orbit.repositories.decisions import DecisionRepository
from orbit.repositories.messages import ChatMessageRepository
from orbit.retrieval import RetrievalService
from orbit.retrieval.rerank import LexicalReranker, RerankUnavailable
from orbit.retrieval.strategies import Candidate, RetrievalRequest

MD = ("# Guide\n\n## Alpha\n\nalpha notes about widgets and gadgets\n\n## Beta\n\nbeta notes about the quartz index size limit\n\n"
      "## Gamma\n\ngamma notes about gadgets\n\n## Delta\n\ndelta notes about widgets\n")
QUERY = "notes"
QUARTZ = "quartz index size limit"


class Reverse:
    name = "reverse"

    def rerank(self, query, candidates):
        return [c.record_id for c in reversed(list(candidates))]


class Broken:
    name = "broken"

    def rerank(self, query, candidates):
        raise RerankUnavailable("model missing")


class Dropper:
    name = "dropper"

    def rerank(self, query, candidates):
        return [c.record_id for c in candidates][:-1]


class System1Reverse:
    name = "julia-1"

    def __init__(self):
        self.calls = []

    def rerank(self, query, candidates):
        self.calls.append((query, list(candidates)))
        return [c.record_id for c in reversed(list(candidates))]


class System1Broken:
    name = "julia-1"

    def rerank(self, query, candidates):
        raise RuntimeError("private candidate text must not appear")


class System1Malformed:
    name = "julia-1"

    def rerank(self, query, candidates):
        return [c.record_id for c in candidates][:-1]


@pytest.fixture()
def env(tmp_path):
    class E:
        pass

    e = E()
    e.conn = connect(tmp_path / "m.db")
    e.docs = tmp_path / "d.db"
    with PageIndexStore(e.docs) as store:
        index_markdown_text(store, "p", "g.md", MD)
        index_markdown_text(store, "other", "g.md", MD)
    e.service = lambda **kw: RetrievalService(e.conn, sections=e.docs, **kw)
    return e


def order(bundle):
    return [i.record_id for i in bundle.items if i.record_kind == "document_section"]


def test_disabled_reranker_is_identical_to_baseline(env):
    plain = env.service().retrieve_context("p", QUERY, 5000)
    assert plain.rendered_context == env.service(section_reranker=None).retrieve_context("p", QUERY, 5000).rendered_context


def test_reranker_reorders_but_never_drops_sections(env):
    plain = order(env.service().retrieve_context("p", QUERY, 9000))
    service = env.service(section_reranker=Reverse())
    flipped = order(service.retrieve_context("p", QUERY, 9000))
    assert sorted(plain) == sorted(flipped) and plain != flipped
    trace = service.last_diagnostics["rerank"]
    assert trace["reranker"] == "reverse" and set(trace["before"]) == set(trace["after"])


def test_lexical_reranker_runs_inside_the_service(env):
    service = env.service(section_reranker=LexicalReranker())
    bundle = service.retrieve_context("p", QUERY, 9000)
    trace = service.last_diagnostics["rerank"]
    assert trace["reranker"] == "lexical" and sorted(trace["before"]) == sorted(trace["after"]) and order(bundle)


def test_shortlist_is_bounded_and_the_tail_keeps_its_order(env):
    service = env.service(section_reranker=Reverse(), rerank_shortlist=2)
    service.retrieve_context("p", QUERY, 9000)
    trace = service.last_diagnostics["rerank"]
    assert trace["shortlist"] == 2 and trace["after"][2:] == trace["before"][2:]
    with pytest.raises(ValueError):
        env.service(rerank_shortlist=1)


def test_strong_keyword_matches_stay_ahead_of_reranked_sections(env):
    service = env.service(section_reranker=Reverse())
    service.retrieve_context("p", "notes about gadgets", 9000)  # Alpha and Gamma contain every term: strict hits
    after = service.last_diagnostics["rerank"]["after"]
    assert service.last_diagnostics["strategies"]["sections"]["fts_tier"] in {"strict", "no_stopwords"}
    assert set(after[:2]) == {r for r in after if r.endswith(("#0002", "#0004"))}  # Reverse() would have put Delta first


def test_unavailable_or_inconsistent_reranker_keeps_the_original_order_with_a_warning(env):
    plain = env.service().retrieve_context("p", QUERY, 9000)
    for reranker, text in ((Broken(), "section reranker unavailable"), (Dropper(), "inconsistent")):
        service = env.service(section_reranker=reranker)
        bundle = service.retrieve_context("p", QUERY, 9000)
        assert bundle.rendered_context == plain.rendered_context
        assert any(text in w for w in service.last_retrieval.warnings)


def test_chat_decisions_isolation_budget_and_determinism_are_unaffected(env):
    m = ChatMessageRepository(env.conn).insert("p", "c", "user", "widgets quartz index size limit chat note")
    repo = DecisionRepository(env.conn)
    repo.save(project="p", key="ok", value="quartz index size limit decision", source_message_id=m, status="draft")
    repo.update_status("p", "ok", "approved")
    repo.save(project="p", key="dr", value="quartz index size limit draft", source_message_id=m, status="draft")
    service = env.service(section_reranker=Reverse(), section_top_k=2)
    first = service.retrieve_context("p", QUARTZ, 900)
    again = env.service(section_reranker=Reverse(), section_top_k=2).retrieve_context("p", QUARTZ, 900)
    assert first.rendered_context == again.rendered_context and first.token_count <= 900
    assert first.items[0].record_kind == "canonical_decision" and first.items[0].status == "approved"
    assert all(i.status != "draft" for i in first.items) and all(i.project_id == "p" for i in first.items)
    assert any(i.record_kind == "chat_message" for i in service.retrieve_context("p", QUARTZ, 9000).items)
    assert service.retrieve_context("nobody", QUARTZ, 9000).items == ()


def test_empty_candidate_sets_are_safe(env):
    service = env.service(section_reranker=LexicalReranker())
    assert service.retrieve_context("p", "zzzz qqqq xxxx wwww vvvv", 5000).items == ()


def _system1_fixture_data(env):
    messages = ChatMessageRepository(env.conn)
    source = messages.insert("p", "c", "user", "notes quartz project source")
    messages.insert("p", "c", "user", "notes quartz another memory")
    messages.insert("p", "c", "user", "notes quartz third memory")
    messages.insert("other", "c", "user", "notes quartz must stay outside project")
    repo = DecisionRepository(env.conn)
    for key in ("approved-a", "approved-b"):
        repo.save(project="p", key=key, value="notes quartz approved decision", source_message_id=source)
        repo.update_status("p", key, "approved")
    draft = repo.save(project="p", key="draft", value="notes quartz draft decision", source_message_id=source)
    return f"decision:{draft['id']}"


def test_system1_receives_only_project_scoped_and_approved_decision_candidates(env):
    draft_id = _system1_fixture_data(env)
    model = System1Reverse()
    service = env.service(system1_reranker=model)
    service.retrieve_context("p", "notes", 9000)
    seen = [candidate for _, group in model.calls for candidate in group]
    assert {candidate.record_type for candidate in seen} == {
        "chat_message", "canonical_decision", "document_section"
    }
    assert all(candidate.project == "p" for candidate in seen)
    decisions = [candidate for candidate in seen if candidate.record_type == "canonical_decision"]
    assert len(decisions) == 2 and {candidate.status for candidate in decisions} == {"approved"}
    assert all(candidate.record_id != draft_id for candidate in seen)
    assert service.last_diagnostics["rerank"]["reranker"] == "julia-1"
    assert service.last_sources


def test_system1_preserves_strong_exact_fts_evidence_and_shortlist_tail(env):
    model = System1Reverse()
    service = env.service(system1_reranker=model, rerank_shortlist=2)
    service.retrieve_context("p", "notes about gadgets", 9000)
    section_group = service.last_diagnostics["system1"]["document_section"]
    assert section_group["after"][2:] == section_group["before"][2:]
    # Strict section-FTS matches are pinned in their original order even if the model reverses them.
    strong = [candidate.record_id for _, group in model.calls for candidate in group
              if candidate.record_type == "document_section"]
    assert section_group["after"][:len(strong)] == strong


def test_system1_preserves_baseline_score_scale_and_overflow_scores(env):
    model = System1Reverse()
    service = env.service(system1_reranker=model, rerank_shortlist=2)
    candidates = {
        "a": Candidate("a", "chat_message", "p", "a", None, None, "semantic", 1, None),
        "b": Candidate("b", "chat_message", "p", "b", None, None, "semantic", 2, None),
        "c": Candidate("c", "chat_message", "p", "c", None, None, "semantic", 3, None),
    }
    baseline_scores = {"a": -0.4, "b": -0.2, "c": -0.1}
    reranked_scores = service._rerank_system1(
        "chat_message", RetrievalRequest("p", "query", 20, 1000), candidates, baseline_scores, {}
    )
    assert reranked_scores["b"] == baseline_scores["a"]
    assert reranked_scores["a"] == pytest.approx(baseline_scores["b"] + 1e-12)
    assert reranked_scores["c"] == baseline_scores["c"]


@pytest.mark.parametrize("model", [System1Broken(), System1Malformed()])
def test_system1_failure_or_invalid_ids_keeps_baseline_and_emits_safe_warning(env, model):
    _system1_fixture_data(env)
    baseline = env.service().retrieve_context("p", "notes", 9000)
    service = env.service(system1_reranker=model)
    result = service.retrieve_context("p", "notes", 9000)
    assert result.rendered_context == baseline.rendered_context
    assert [i.record_id for i in result.items] == [i.record_id for i in baseline.items]
    assert service.last_diagnostics["rerank"]["failures"] > 0
    warning = " ".join(service.last_retrieval.warnings)
    assert "baseline order retained" in warning
    assert "private candidate text" not in warning
