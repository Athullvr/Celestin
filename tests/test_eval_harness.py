"""Evaluation harness: frozen data, credential handling and result bookkeeping (all offline)."""

import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("pageindex")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "eval"))

import run_eval  # noqa: E402
from tests.pageindex.fakes import FakeLLM  # noqa: E402

# Changing the questions, gold evidence or frozen corpus changes this hash. If you change them
# on purpose, report the old and new comparison side by side (see docs/pageindex.md).
FROZEN_DATASET_SHA256 = "77679aeea136e222ea56bad811a46acdc1e9955da8b033542b09b9dff0d4af95"


def test_dataset_and_corpus_are_frozen():
    assert run_eval.dataset_hash() == FROZEN_DATASET_SHA256


def test_every_question_has_gold_evidence_in_its_listed_documents():
    from orbit.pageindex.tree import build_sections

    for query, evidence, docs in run_eval.DOC_QUERIES:
        found = [d for d in docs for s in build_sections(run_eval.read_doc(d), d) if evidence.lower() in s.text.lower()]
        assert found, f"no gold section for {query!r}"


def test_requiring_the_real_llm_without_credentials_is_an_actionable_error(monkeypatch):
    with pytest.raises(SystemExit) as raised:
        run_eval.check_llm(None, required=True)
    assert "CELESTIN_PAGEINDEX_MODEL" in str(raised.value)
    monkeypatch.setattr(run_eval, "missing_credentials", lambda model: ["OPENAI_API_KEY"])
    with pytest.raises(SystemExit) as raised:
        run_eval.check_llm("openai/x", required=True)
    assert "OPENAI_API_KEY" in str(raised.value)
    assert "OPENAI_API_KEY" in run_eval.check_llm("openai/x", required=False)


def test_default_run_skips_the_real_llm_system_and_labels_diagnostics(tmp_path, monkeypatch):
    monkeypatch.delenv("CELESTIN_PAGEINDEX_MODEL", raising=False)
    monkeypatch.setattr(run_eval, "semantic_for", lambda *a, **k: (None, None))  # keep the test offline
    assert run_eval.main(["--budgets", "20000", "--fts-relax", "off", "--out", str(tmp_path)]) == 0
    data = json.loads((tmp_path / "results_strict_fts.json").read_text())
    assert data["systems"]["N"]["skipped"].startswith("no model")
    assert data["systems"]["SN"]["skipped"].startswith("no model")
    assert {data["systems"][k]["kind"] for k in "HS"} == {"baseline"}
    assert data["systems"]["S"]["budgets"]["20000"]["mean_strategies_run"] <= 3
    assert "fallback_rate" in data["systems"]["S"]["budgets"]["20000"]
    assert data["meta"]["dataset_sha256"] == FROZEN_DATASET_SHA256
    assert data["meta"]["navigation_model"] is None and data["meta"]["fts_relax"] is False
    assert {data["systems"][k]["kind"] for k in "CE"} == {"diagnostic"}
    text = (tmp_path / "results_strict_fts.md").read_text()
    assert "System N skipped" in text and "diagnostic" in text and "not evidence of LLM performance" in text


def test_explicit_real_llm_request_without_model_fails(tmp_path, monkeypatch):
    monkeypatch.delenv("CELESTIN_PAGEINDEX_MODEL", raising=False)
    with pytest.raises(SystemExit):
        run_eval.main(["--systems", "N", "--out", str(tmp_path)])


def test_real_llm_system_bookkeeping_with_a_fake_model(tmp_path, monkeypatch):
    """Exercises the N code path (usage, latency, failures) with a fake model: NOT a quality result."""
    llm = FakeLLM(want=["embedding model decision", "vector store decision"])
    llm.last_usage = {"prompt_tokens": 1000, "completion_tokens": 20}
    monkeypatch.setattr(run_eval, "litellm_chat", lambda model, timeout=60.0, **kw: llm)
    monkeypatch.setattr(run_eval, "missing_credentials", lambda model: [])
    monkeypatch.setattr(run_eval, "semantic_for", lambda *a, **k: (None, None))
    assert run_eval.main(["--systems", "N", "--model", "fake/model", "--budgets", "20000",
                          "--fts-relax", "off", "--out", str(tmp_path)]) == 0
    data = json.loads((tmp_path / "results_strict_fts.json").read_text())
    n = data["systems"]["N"]["budgets"]["20000"]
    assert data["meta"]["navigation_model"] == "fake/model"
    assert n["pageindex_routed"] > 0 and n["pageindex_failures"] == 0
    assert n["observed_prompt_tokens"] == 1000 * n["pageindex_routed"]
    assert n["est_prompt_tokens_mean"] > 0 and "model_latency_ms_mean" in n
    assert len(data["systems"]["N"]["queries"]["20000"]) == len(run_eval.DOC_QUERIES)


def test_model_failures_are_counted_not_hidden(tmp_path, monkeypatch):
    llm = FakeLLM(error=TimeoutError("timeout talking to provider"))
    monkeypatch.setattr(run_eval, "litellm_chat", lambda model, timeout=60.0, **kw: llm)
    monkeypatch.setattr(run_eval, "missing_credentials", lambda model: [])
    monkeypatch.setattr(run_eval, "semantic_for", lambda *a, **k: (None, None))
    run_eval.main(["--systems", "N", "--model", "fake/model", "--budgets", "20000", "--fts-relax", "off", "--out", str(tmp_path)])
    n = json.loads((tmp_path / "results_strict_fts.json").read_text())["systems"]["N"]["budgets"]["20000"]
    assert n["pageindex_failures"] == n["pageindex_routed"] + n["pageindex_failures"] > 0
    assert n["pageindex_timeouts"] == n["pageindex_failures"] and n["answer_in_context"] == 0


FROZEN_HELDOUT_SHA256 = "69e75c0afa5b804672ce202d3145466174c49b2090511ade1b6907ec98603828"


def test_heldout_set_is_frozen_and_dev_set_is_untouched():
    try:
        run_eval.use_dataset("heldout")
        assert run_eval.dataset_hash() == FROZEN_HELDOUT_SHA256
        assert len(run_eval.DOC_QUERIES) == 12
        heldout_questions = {q for q, _, _ in run_eval.DOC_QUERIES}
    finally:
        run_eval.use_dataset("dev")
    assert run_eval.dataset_hash() == FROZEN_DATASET_SHA256
    assert not heldout_questions & {q for q, _, _ in run_eval.DOC_QUERIES}  # no question appears in both sets


def test_heldout_gold_evidence_exists_in_the_frozen_corpus():
    from orbit.pageindex.tree import build_sections
    import heldout

    for query, evidence, docs in heldout.DOC_QUERIES:
        assert any(evidence.lower() in s.text.lower() for d in docs for s in build_sections(run_eval.read_doc(d), d)), query


def test_noise_variants_are_registered_as_selector_variants_with_defaults_off():
    for key in ("S+m04", "S+m08", "S+m12", "S+k5", "S+x1200"):
        spec = run_eval.SPECS[key]
        assert spec.selector == "adaptive" and spec.navigator == "none" and spec.kind == "baseline"
    base = run_eval.SPECS["S"]
    assert (base.section_margin, base.top_k, base.excerpt) == (None, None, None)


def test_noise_sweep_run_records_answers_lost_and_candidate_counts(tmp_path, monkeypatch):
    monkeypatch.setattr(run_eval, "semantic_for", lambda *a, **k: (None, None))  # offline: keyword search only
    assert run_eval.main(["--systems", "S,S+k3", "--budgets", "20000", "--dataset", "heldout", "--out", str(tmp_path)]) == 0
    data = json.loads((tmp_path / "results_heldout.json").read_text())
    assert data["meta"]["dataset"] == "heldout"
    capped = data["systems"]["S+k3"]
    assert "answers_lost_vs_S" in capped and "mean_fused_sections" in capped["budgets"]["20000"]
