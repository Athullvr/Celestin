"""Compare retrieval pipelines on a frozen corpus and question set.

    python eval/run_eval.py                       # local systems; real-LLM system skipped without credentials
    python eval/run_eval.py --systems A,B,F,N     # N = PageIndex with a real LLM (needs credentials)
    python eval/run_eval.py --f-sweep             # selectivity sweep for the section baseline F

Real-LLM system N needs: CELESTIN_PAGEINDEX_MODEL (or --model) naming a LiteLLM model, and that
provider's credentials (for example OPENAI_API_KEY). It sends outlines and questions to the provider
and costs money; the run prints the number of calls it will make. Without credentials, asking for N
explicitly (or --require-llm) exits with an actionable error.

Systems
  A  baseline          each document ingested as ONE chat message; FTS5 only
  B  baseline+semantic same, plus semantic search (real embedding model; needs the cached model)
  F  sections+semantic every heading section ingested as its own message; FTS5 + semantic
                       (no PageIndex; the strongest practical baseline so far)
  H  heading sections  PRODUCT path: documents indexed with celestin-docs, FTS5 + semantic over
                       sections, all strategies run (no PageIndex)
  J  System 1         as H plus pinned local Julia-1 candidate reranking (requires local model path)
  L  System 1         as H plus pinned local Laya candidate reranking (requires cached Laya model)
  S  adaptive selector PRODUCT path: as H but CELESTIN_RETRIEVAL_SELECTOR=adaptive (one primary
                       strategy + at most one fallback, no PageIndex)
  N  PageIndex, real LLM navigation + FTS5 + semantic         [real-LLM evidence]
  SN adaptive selector with real-LLM PageIndex available as primary/fallback  [real-LLM evidence]
  C  DIAGNOSTIC: PageIndex plumbing with a lexical stand-in navigator, FTS5 only
  D  DIAGNOSTIC: as C plus semantic
  E  DIAGNOSTIC: oracle navigator told the answer (upper bound, not achievable)
  Sd DIAGNOSTIC: adaptive selector with the lexical stand-in navigator as PageIndex
C, D and E are NOT evidence of LLM performance. Chat memories are ingested in every system.
Corpus: eval/corpus (frozen). Questions: eval/dataset.py (frozen, hashed into the results).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import heldout as _heldout
import rerank_challenge as _challenge
from dataset import CHAT_MESSAGES, CHAT_QUERIES, DATASET_VERSION, DOC_QUERIES, DOCS
from standin import OracleNavigator, StandInNavigator

from orbit.database.engine import connect
from orbit.pageindex.backend import PageIndexBackend
from orbit.pageindex.indexer import index_markdown_text
from orbit.pageindex.navigator import LLMTreeNavigator, litellm_chat, missing_credentials
from orbit.pageindex.store import PageIndexStore
from orbit.pageindex.tree import build_sections
from orbit.repositories.messages import ChatMessageRepository
from orbit.retrieval import RetrievalService
from orbit.retrieval.rerank import build_reranker
from orbit.retrieval.service import (
    LAYA_MODEL_REPO, LAYA_MODEL_REVISION, LAYA_TIMEOUT_SECONDS, LayaCandidateReranker,
    _get_laya_agent, build_laya_reranker,
)
from orbit.retrieval.system1 import build_julia1_reranker

HERE = Path(__file__).parent
CORPUS = HERE / "corpus"
PROJECT = "eval"
MAX_SECTIONS = 3
DEFAULT_BUDGETS = (2_000, 20_000)


@dataclass(frozen=True)
class Spec:
    key: str
    label: str
    kind: str  # baseline | system1 | real_llm | diagnostic
    docs: str  # whole | sections | tree
    semantic: bool = False
    navigator: str = "none"  # none | standin | oracle | llm
    candidate_limit: int = 100
    margin: float | None = None
    selector: str = "all"
    section_margin: float | None = None
    top_k: int | None = None
    excerpt: int | None = None
    rerank: str | None = None
    system1: bool = False
    system1_backend: str = "julia"


SPECS = {s.key: s for s in [
    Spec("A", "A original: docs as messages, FTS5", "baseline", "whole"),
    Spec("B", "B A + semantic", "baseline", "whole", semantic=True),
    Spec("F", "F sections as messages + semantic (no PageIndex)", "baseline", "sections", semantic=True),
    Spec("N", "N PageIndex, REAL LLM + FTS5 + semantic", "real_llm", "tree", semantic=True, navigator="llm"),
    Spec("H", "H heading sections: FTS5 + semantic (product, no PageIndex)", "baseline", "store", semantic=True),
    Spec("J", "J H + local Julia-1 System 1 reranking", "system1", "store", semantic=True, system1=True),
    Spec("L", "L H + local Laya System 1 reranking", "system1", "store", semantic=True, system1=True,
         system1_backend="laya"),
    Spec("S", "S deterministic adaptive selector (product, no PageIndex)", "baseline", "store", semantic=True,
         selector="adaptive"),
    Spec("SN", "SN adaptive selector + REAL LLM PageIndex", "real_llm", "store", semantic=True, selector="adaptive",
         navigator="llm"),
    Spec("Sd", "Sd diagnostic: adaptive selector + stand-in navigator", "diagnostic", "store", semantic=True,
         selector="adaptive", navigator="standin"),
    Spec("C", "C diagnostic: stand-in navigator + FTS5", "diagnostic", "tree", navigator="standin"),
    Spec("D", "D diagnostic: stand-in navigator + semantic", "diagnostic", "tree", semantic=True, navigator="standin"),
    Spec("E", "E diagnostic: oracle navigator (upper bound)", "diagnostic", "tree", navigator="oracle"),
]}
for k, margin in (("3", None), ("5", None), ("10", None)):
    SPECS[f"F@{k}"] = Spec(f"F@{k}", f"F with candidate_limit={k}", "baseline", "sections", semantic=True,
                           candidate_limit=int(k))
for m in (0.04, 0.08, 0.12):
    SPECS[f"F~{m}"] = Spec(f"F~{m}", f"F with relative margin {m}", "baseline", "sections", semantic=True, margin=m)
def _variant(key, label, **kw):
    SPECS[key] = Spec(key, label, "baseline", "store", semantic=True, selector="adaptive", **kw)


for m in (0.04, 0.08, 0.12):
    _variant(f"S+m{int(m * 100):02d}", f"S + section margin {m}", section_margin=m)
for k in (3, 5, 8):
    _variant(f"S+k{k}", f"S + top-{k} sections", top_k=k)
_variant("S+x1200", "S + excerpts (1200 B)", excerpt=1200)
_variant("S+m08+k5", "S + margin 0.08 + top-5", section_margin=0.08, top_k=5)
_variant("S+m08+x1200", "S + margin 0.08 + excerpts", section_margin=0.08, excerpt=1200)
_variant("S+m04+x1200", "S + margin 0.04 + excerpts", section_margin=0.04, excerpt=1200)
for r, label in (("lexical", "lexical"), ("cross_encoder", "cross-encoder"), ("cross_encoder_rrf", "cross-encoder + RRF")):
    key = {"lexical": "lex", "cross_encoder": "ce", "cross_encoder_rrf": "cerrf"}[r]
    _variant(f"S+r-{key}", f"S + rerank ({label})", rerank=r)
    _variant(f"S+m08+r-{key}", f"S + margin 0.08 + rerank ({label})", section_margin=0.08, rerank=r)
for k in (5, 8):
    _variant(f"S+r-ce+k{k}", f"S + rerank (cross-encoder) + top-{k}", rerank="cross_encoder", top_k=k)
_variant("S+m08+r-ce+k8", "S + margin 0.08 + rerank (cross-encoder) + top-8", section_margin=0.08,
         rerank="cross_encoder", top_k=8)
_variant("S+m08+r-cerrf+k8", "S + margin 0.08 + rerank (cross-encoder + RRF) + top-8", section_margin=0.08,
         rerank="cross_encoder_rrf", top_k=8)
RERANK_SWEEP = ["S", "S+m08", "S+r-lex", "S+r-ce", "S+r-cerrf", "S+m08+r-lex", "S+m08+r-ce", "S+m08+r-cerrf",
                "S+r-ce+k5", "S+r-ce+k8", "S+m08+r-ce+k8", "S+m08+r-cerrf+k8"]
NOISE_SWEEP = ["H", "S", "S+m04", "S+m08", "S+m12", "S+k3", "S+k5", "S+k8", "S+x1200", "S+m08+k5", "S+m08+x1200"]
SWEEP = ["F", "F@10", "F@5", "F@3", "F~0.12", "F~0.08", "F~0.04"]


def read_doc(name: str) -> str:
    return (CORPUS / name).read_text()


DATASET_NAME = "dev"


def use_dataset(name: str) -> None:
    """Switch the question set (corpus is always the same frozen snapshot)."""
    global DOC_QUERIES, CHAT_MESSAGES, CHAT_QUERIES, DATASET_NAME
    if name == "heldout":
        DOC_QUERIES, CHAT_MESSAGES, CHAT_QUERIES = _heldout.DOC_QUERIES, _heldout.CHAT_MESSAGES, _heldout.CHAT_QUERIES
    elif name == "rerank_challenge":
        DOC_QUERIES, CHAT_MESSAGES, CHAT_QUERIES = _challenge.DOC_QUERIES, _challenge.CHAT_MESSAGES, _challenge.CHAT_QUERIES
    elif name == "dev":
        from dataset import CHAT_MESSAGES as cm, CHAT_QUERIES as cq, DOC_QUERIES as dq
        DOC_QUERIES, CHAT_MESSAGES, CHAT_QUERIES = dq, cm, cq
    else:
        raise ValueError(f"unknown dataset {name!r}")
    DATASET_NAME = name


def corpus_hash() -> str:
    """Stable hash of the named corpus files, independent of the question set."""
    files = [(name, hashlib.sha256(read_doc(name).encode()).hexdigest()) for name in DOCS]
    payload = json.dumps(files, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def dataset_hash() -> str:
    version = {
        "dev": DATASET_VERSION,
        "heldout": f"heldout-{_heldout.HELDOUT_VERSION}",
        "rerank_challenge": f"rerank-challenge-{_challenge.VERSION}",
    }[DATASET_NAME]
    payload = json.dumps([version, DOCS, DOC_QUERIES, CHAT_MESSAGES, CHAT_QUERIES], sort_keys=True)
    corpus = "".join(hashlib.sha256(read_doc(d).encode()).hexdigest() for d in DOCS)
    return hashlib.sha256((payload + corpus).encode()).hexdigest()


def git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              cwd=HERE, check=True).stdout.strip()
    except Exception:
        return "unknown"


def working_tree_dirty() -> bool:
    try:
        status = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True,
                                cwd=HERE, check=True).stdout
        return bool(status.strip())
    except Exception:
        return True


def semantic_for(db_dir: Path, conn, spec: Spec, docs_path: Path | None = None):
    from orbit.semantic.config import get_provider, load_settings
    from orbit.semantic.indexer import Indexer
    from orbit.semantic.search import SemanticSearch
    from orbit.semantic.vector_index import VectorIndex

    settings = load_settings(db_dir / "main.db")
    provider = get_provider(settings)
    store = PageIndexStore(docs_path, create=False) if docs_path else None
    with VectorIndex(db_dir / "v.db", model_id=provider.model_id, dimension=provider.dimension) as index:
        report = Indexer(conn, provider, index, sections_connection=store.connection() if store else None).sync()
    if store:
        store.close()
    return SemanticSearch(provider, db_dir / "v.db", settings.min_similarity, relative_margin=spec.margin,
                          section_margin=spec.section_margin), report


FTS_RELAX = True


def build_system(spec: Spec, tmp: Path, model: str | None, sections_by_key: dict,
                 system1_model_path: str | None = None):
    conn = connect(tmp / "main.db")
    messages = ChatMessageRepository(conn)
    ids: dict[str, tuple[str, str | None]] = {}
    for text in CHAT_MESSAGES:
        messages.insert(PROJECT, "chat", "user", text)
    records = len(CHAT_MESSAGES)
    t0 = time.perf_counter()
    backend = navigator = None
    if spec.docs == "whole":
        for d in DOCS:
            ids[str(messages.insert(PROJECT, "docs", "user", read_doc(d)))] = (d, None)
            records += 1
    elif spec.docs == "sections":
        for d in DOCS:
            for sec in build_sections(read_doc(d), Path(d).stem):
                ids[str(messages.insert(PROJECT, d, "user", f"{' > '.join(sec.path)}\n{sec.text}"))] = (d, sec.node_id)
                records += 1
    else:
        with PageIndexStore(tmp / "docs.db") as store:
            for d in DOCS:
                index_markdown_text(store, PROJECT, d, read_doc(d))
        if spec.navigator == "none":
            navigator = None
        elif spec.navigator == "llm":
            llm = litellm_chat(model, timeout=60.0)
            navigator = LLMTreeNavigator(llm)
        elif spec.navigator == "oracle":
            navigator = OracleNavigator(sections_by_key)
        else:
            navigator = StandInNavigator()
        if navigator is not None:
            backend = PageIndexBackend(tmp / "docs.db", navigator, max_sections=MAX_SECTIONS, cache_size=0)
        records += len(sections_by_key)
    semantic = None
    if spec.semantic:
        semantic, _ = semantic_for(tmp, conn, spec, tmp / "docs.db" if spec.docs == "store" else None)
    index_secs = time.perf_counter() - t0
    system1_reranker = None
    if spec.system1_backend == "julia" and spec.system1:
        system1_reranker = build_julia1_reranker(system1_model_path)
    elif spec.system1_backend == "laya" and spec.system1:
        from orbit.retrieval.service import build_laya_reranker
        system1_reranker = build_laya_reranker()
    service = RetrievalService(conn, semantic=semantic, documents=backend, candidate_limit=spec.candidate_limit,
                               fts_relax=FTS_RELAX, selector=spec.selector,
                               sections=tmp / "docs.db" if spec.docs == "store" else None,
                               section_top_k=spec.top_k, section_excerpt_bytes=spec.excerpt,
                               section_reranker=build_reranker(spec.rerank),
                               system1_reranker=system1_reranker)
    return service, ids, index_secs, navigator, records


def judge(item, evidence, gold_docs, ids, sections):
    """(document source correct, section source correct) for one context item."""
    if item.record_kind == "document_section":
        doc, node = item.source_id, item.record_id.rsplit("#", 1)[1]
    else:
        doc, node = ids.get(item.record_id, (None, None))
    sec = sections.get((doc, node)) if node else None
    return doc in gold_docs, bool(sec and doc in gold_docs and evidence.lower() in sec.text.lower())


def gold_snippets(evidence, gold_docs, sections):
    """Text of each gold section (first 80 chars after the heading) for content-based recall."""
    out = []
    for (d, _), s in sections.items():
        if d in gold_docs and evidence.lower() in s.text.lower():
            body = s.text.split("\n", 1)[-1].strip() or s.text
            out.append(body[:80])
    return out


def _has_evidence(record_id: str, evidence: str, sections) -> bool:
    if not record_id.startswith("doc:"):
        return False
    doc, node = record_id[4:].rsplit("#", 1)
    sec = sections.get((doc, node))
    return bool(sec and evidence.lower() in sec.text.lower())


def run_query(service, query, budget, evidence, gold_docs, ids, sections, navigator):
    if isinstance(navigator, OracleNavigator):
        navigator.target = (evidence, gold_docs)
    t0 = time.perf_counter()
    bundle = service.retrieve_context(PROJECT, query, budget)
    total_ms = (time.perf_counter() - t0) * 1000
    info = service.last_retrieval
    nav = info.navigation or {}
    snippets = gold_snippets(evidence, gold_docs, sections)
    doc_ok = sec_ok = False
    first = None
    for rank, item in enumerate(bundle.items, start=1):
        d, s = judge(item, evidence, gold_docs, ids, sections)
        doc_ok |= d
        sec_ok |= s
        if first is None and evidence.lower() in item.content.lower():
            first = rank
    answering = [i for i in bundle.items if evidence.lower() in i.content.lower()]
    covered = sum(any(sn in i.content for i in bundle.items) for sn in snippets)
    status = info.pageindex or "n/a"
    sel = info.selector or {}
    rr = service.last_diagnostics.get("rerank") or {}
    warnings = service.last_retrieval.warnings
    ranked_after = rr.get("after") or [rid for rid in (service.last_diagnostics.get("section_order") or [])]
    ranked_before = rr.get("before") or ranked_after
    gold_pos = lambda order: next((i for i, rid in enumerate(order, start=1) if _has_evidence(rid, evidence, sections)), None)
    pos_before, pos_after = gold_pos(ranked_before), gold_pos(ranked_after)
    gold_candidates = [rid for rid in ranked_after if _has_evidence(rid, evidence, sections)]
    selected = {i.record_id for i in bundle.items}
    if answering:
        reason = None
    elif not gold_candidates:
        reason = "no candidate section contains the answer (not retrieved, or removed by margin/filters)"
    elif not (set(gold_candidates) & selected):
        reason = "answer-bearing candidate present but excluded by the byte budget or ranked below the fill"
    else:
        reason = "unclassified"
    return {
        "section_order_before": ranked_before, "section_order_after": ranked_after,
        "gold_pos_before": pos_before, "gold_pos_after": pos_after, "miss_reason": reason,
        "rerank_ms": rr.get("ms", 0.0), "answered": bool(answering), "doc_ok": doc_ok, "sec_ok": sec_ok,
        "system1_failures": rr.get("failures", 0),
        "system1_timeouts": sum("(TimeoutError)" in warning for warning in warnings),
        "system1_input_skips": rr.get("input_skips", 0),
        "system1_calls": sum(group.get("calls", 0) for group in rr.get("groups", {}).values()),
        "system1_call_ms": sum(group.get("ms", 0.0) for group in rr.get("groups", {}).values()
                                if group.get("calls")),
        "gold_recall": covered / len(snippets) if snippets else 0.0,
        "rr": 1 / first if first else 0.0, "tokens": bundle.token_count, "items": len(bundle.items),
        "unrelated_item_rate": (len(bundle.items) - len(answering)) / len(bundle.items) if bundle.items else 0.0,
        "density": sum(len(i.content.encode()) for i in answering) / max(1, len(bundle.rendered_context.encode())),
        "budget_excluded": sum(e.reason == "token_budget" for e in bundle.excluded),
        "total_ms": total_ms, "model_ms": nav.get("elapsed_ms", 0.0) if not nav.get("cache_hit") else 0.0,
        "pageindex": status.split(":")[0] if status != "n/a" else "n/a",
        "pageindex_failed": status.startswith("unavailable"),
        "pageindex_timeout": status.startswith("unavailable") and "timeout" in status.lower(),
        "usage": nav.get("usage"), "est_prompt_tokens": nav.get("est_prompt_tokens"),
        "primary": sel.get("primary"), "fallback_used": bool(sel.get("fallback_used")),
        "strategies_run": len(service._executed),
        "context_bytes": len(bundle.rendered_context.encode()),
        "fused_sections": service.last_diagnostics.get("fused", {}).get("document_section", 0),
        "capped_sections": service.last_diagnostics.get("capped_sections", 0),
        "selected_sections": sum(i.record_kind == "document_section" for i in bundle.items),
        "semantic_section_filter": service.last_diagnostics.get("semantic_filter", {}).get("document_section"),
    }


def _percentile(values, percentile):
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, int((len(ordered) * percentile + 0.999999) - 1)))]


def aggregate(rows, chat_hits, model, chat_rerank_ms=(), chat_system1_failures=(), chat_system1_calls=(),
              chat_system1_call_ms=(), chat_system1_timeouts=(), chat_system1_input_skips=()):
    n = len(rows)
    mean = lambda key: statistics.mean(r[key] for r in rows)
    routed = [r for r in rows if r["pageindex"] == "used"]
    observed = [r["usage"] for r in routed if r["usage"]]
    out = {
        "answer_in_context": mean("answered"), "doc_source_accuracy": mean("doc_ok"),
        "section_source_accuracy": mean("sec_ok"), "gold_section_recall": mean("gold_recall"), "mrr": mean("rr"),
        "mean_context_bytes": mean("context_bytes"),
        "median_context_bytes": statistics.median(r["context_bytes"] for r in rows),
        "mean_context_tokens": mean("tokens"),
        "median_context_tokens": statistics.median(r["tokens"] for r in rows),
        "mean_items": mean("items"),
        "unrelated_item_rate": mean("unrelated_item_rate"), "answer_share_of_context": mean("density"),
        "queries_with_budget_exclusions": sum(r["budget_excluded"] > 0 for r in rows),
        "mean_total_latency_ms": mean("total_ms"),
        "p50_total_latency_ms": _percentile([r["total_ms"] for r in rows], 0.50),
        "p95_total_latency_ms": _percentile([r["total_ms"] for r in rows], 0.95),
        "mean_local_latency_ms": statistics.mean(r["total_ms"] - r["model_ms"] for r in rows),
        "chat_recall": sum(chat_hits) / len(chat_hits),
        "fallback_rate": mean("fallback_used"), "mean_strategies_run": mean("strategies_run"),
        "primary_strategies": {p: sum(r["primary"] == p for r in rows) for p in sorted({r["primary"] for r in rows if r["primary"]})},
        "pageindex_routed": len(routed), "pageindex_skipped": sum(r["pageindex"] == "skipped" for r in rows),
        "pageindex_failures": sum(r["pageindex_failed"] for r in rows),
        "pageindex_timeouts": sum(r["pageindex_timeout"] for r in rows),
        "queries": n,
        "gold_mrr_before_rerank": statistics.mean(1 / r["gold_pos_before"] if r["gold_pos_before"] else 0 for r in rows),
        "gold_mrr_after_rerank": statistics.mean(1 / r["gold_pos_after"] if r["gold_pos_after"] else 0 for r in rows),
        "gold_median_pos_before": statistics.median(r["gold_pos_before"] or 99 for r in rows),
        "gold_median_pos_after": statistics.median(r["gold_pos_after"] or 99 for r in rows),
        "answers_per_kb": sum(r["answered"] for r in rows) / max(1e-9, sum(r["context_bytes"] for r in rows) / 1000),
        "gold_recall_per_kb": sum(r["gold_recall"] for r in rows) / max(1e-9, sum(r["context_bytes"] for r in rows) / 1000),
        "mean_rerank_ms": mean("rerank_ms"),
        "system1_inference_failures": sum(r.get("system1_failures", 0) for r in rows) + sum(chat_system1_failures),
        "system1_timeouts": sum(r.get("system1_timeouts", 0) for r in rows) + sum(chat_system1_timeouts),
        "system1_input_skips": sum(r.get("system1_input_skips", 0) for r in rows) + sum(chat_system1_input_skips),
        "system1_inference_calls": sum(r.get("system1_calls", 0) for r in rows) + sum(chat_system1_calls),
        "system1_inference_ms": sum(r.get("system1_call_ms", 0.0) for r in rows) + sum(chat_system1_call_ms),
        "p95_system1_query_ms": _percentile(
            [r.get("system1_call_ms", 0.0) for r in rows] + list(chat_system1_call_ms), 0.95
        ),
        "mean_system1_inference_ms": (
            (sum(r.get("system1_call_ms", 0.0) for r in rows) + sum(chat_system1_call_ms)) /
            (sum(r.get("system1_calls", 0) for r in rows) + sum(chat_system1_calls))
            if (sum(r.get("system1_calls", 0) for r in rows) + sum(chat_system1_calls)) else 0.0
        ),
        "mean_system1_rerank_ms": statistics.mean(
            [r["rerank_ms"] for r in rows] + list(chat_rerank_ms)
        ) if rows or chat_rerank_ms else 0.0,
        "mean_fused_sections": mean("fused_sections"), "mean_capped_sections": mean("capped_sections"),
        "mean_selected_sections": mean("selected_sections"),
    }
    if routed:
        times = sorted(r["model_ms"] for r in routed)
        out["model_latency_ms_mean"] = statistics.mean(times)
        out["model_latency_ms_p95"] = times[min(len(times) - 1, int(0.95 * len(times)))]
        out["est_prompt_tokens_mean"] = statistics.mean(r["est_prompt_tokens"] or 0 for r in routed)
    if observed:
        prompt = sum(u.get("prompt_tokens") or 0 for u in observed)
        completion = sum(u.get("completion_tokens") or 0 for u in observed)
        out["observed_prompt_tokens"], out["observed_completion_tokens"] = prompt, completion
        try:
            import litellm
            p, c = litellm.cost_per_token(model=model, prompt_tokens=prompt, completion_tokens=completion)
            out["estimated_cost_usd"] = round(p + c, 6)  # from LiteLLM's price table; an estimate
        except Exception:
            out["estimated_cost_usd"] = None
    return out


def run_system(spec, sections, budgets, model, system1_model_path=None, *, repeats=1, system1_runtime=None):
    with tempfile.TemporaryDirectory() as t:
        service, ids, index_secs, navigator, records = build_system(
            spec, Path(t), model, sections, system1_model_path
        )
        out = {"label": spec.label, "kind": spec.kind, "index_seconds": round(index_secs, 2),
               "records_indexed": records, "budgets": {}, "queries": {}, "chat_queries": {}}
        if spec.system1:
            out["system1_runtime"] = system1_runtime
        for budget in budgets:
            rows = []
            chat = []
            chat_rows = []
            for repeat in range(repeats):
                for query, evidence, gold_docs in DOC_QUERIES:
                    row = run_query(service, query, budget, evidence, gold_docs, ids, sections, navigator)
                    rows.append({"repeat": repeat + 1, "query": query, **row})
                for query, evidence in CHAT_QUERIES:
                    t_chat = time.perf_counter()
                    bundle = service.retrieve_context(PROJECT, query, budget)
                    chat_total_ms = (time.perf_counter() - t_chat) * 1000
                    chat_rr = service.last_diagnostics.get("rerank") or {}
                    warnings = service.last_retrieval.warnings
                    answered = any(evidence.lower() in i.content.lower() for i in bundle.items if i.record_kind == "chat_message")
                    chat.append(answered)
                    chat_rows.append({
                        "repeat": repeat + 1, "query": query, "answered": answered,
                        "miss_reason": None if answered else "gold chat evidence absent from returned chat items",
                        "total_ms": chat_total_ms, "rerank_ms": chat_rr.get("ms", 0.0),
                        "system1_failures": chat_rr.get("failures", 0),
                        "system1_timeouts": sum("(TimeoutError)" in warning for warning in warnings),
                        "system1_input_skips": chat_rr.get("input_skips", 0),
                        "system1_calls": sum(group.get("calls", 0) for group in chat_rr.get("groups", {}).values()),
                        "system1_call_ms": sum(group.get("ms", 0.0) for group in chat_rr.get("groups", {}).values()
                                                if group.get("calls")),
                    })
            out["budgets"][budget] = aggregate(
                rows, chat, model,
                [r["rerank_ms"] for r in chat_rows],
                [r["system1_failures"] for r in chat_rows],
                [r["system1_calls"] for r in chat_rows],
                [r["system1_call_ms"] for r in chat_rows],
                [r["system1_timeouts"] for r in chat_rows],
                [r["system1_input_skips"] for r in chat_rows],
            )
            out["queries"][budget] = rows
            out["chat_queries"][budget] = chat_rows
        return out


def check_llm(model: str | None, required: bool) -> str | None:
    """Return a reason N cannot run, or None. Exits with guidance when N is required."""
    reason = None
    if not model:
        reason = "no model: set CELESTIN_PAGEINDEX_MODEL (or --model) to a LiteLLM model name, e.g. openai/gpt-4o-mini"
    else:
        try:
            import litellm  # noqa: F401
        except ImportError:
            reason = "litellm is not installed: pip install -e '.[pageindex]'"
        else:
            missing = missing_credentials(model)
            if missing:
                reason = f"missing credentials for {model}: set {', '.join(missing)} in the environment"
    if reason and required:
        sys.exit(f"ERROR: cannot run the real-LLM system N: {reason}")
    return reason


def check_system1(model_path: str | None, required: bool):
    """Preflight the pinned local Julia-1 runtime before any J-vs-baseline run."""
    if not model_path:
        reason = "no local Julia-1 checkout/checkpoint: set CELESTIN_SYSTEM1_MODEL_PATH or --system1-model-path"
        if required:
            sys.exit(f"ERROR: cannot run system J: {reason}")
        return reason, None
    try:
        runtime = build_julia1_reranker(model_path).health_check()
    except Exception as exc:
        reason = f"Julia-1 preflight failed ({type(exc).__name__}): {exc}"
        if required:
            sys.exit(f"ERROR: cannot run system J: {reason}")
        return reason, None
    return None, runtime


def _rss_bytes() -> int | None:
    try:
        with open("/proc/self/status", encoding="ascii") as stream:
            for line in stream:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def check_laya(required: bool):
    """Verify the pinned local Laya checkpoint and record cold-load/warmup resources."""
    try:
        from huggingface_hub import snapshot_download
        import laya
        import torch

        checkpoint_dir = Path(snapshot_download(
            repo_id=LAYA_MODEL_REPO, revision=LAYA_MODEL_REVISION, local_files_only=True
        ))
        weight_suffixes = {".safetensors", ".bin", ".pt", ".pth"}
        checkpoint_bytes = sum(path.stat().st_size for path in checkpoint_dir.rglob("*")
                                if path.is_file() and path.suffix in weight_suffixes)
        if checkpoint_bytes <= 0:
            raise FileNotFoundError("pinned Laya checkpoint weights are not cached")
        rss_before = _rss_bytes()
        started = time.perf_counter()
        agent = _get_laya_agent()
        load_ms = (time.perf_counter() - started) * 1000
        rss_loaded = _rss_bytes()
        warmup_payloads = [
            {"record_id": "warmup-a", "baseline_rank": 1,
             "state": json.dumps({"query": "Where is the example setting?", "candidate_type": "document_section",
                                  "candidate_text": "The example setting is configured locally.",
                                  "retrieval_evidence": [{"method": "fts", "rank": 1, "score": -0.1}]})},
            {"record_id": "warmup-b", "baseline_rank": 2,
             "state": json.dumps({"query": "Where is the example setting?", "candidate_type": "document_section",
                                  "candidate_text": "This unrelated note contains no setting details.",
                                  "retrieval_evidence": [{"method": "semantic", "rank": 2, "score": 0.4}]})},
        ]
        started = time.perf_counter()
        ranked = LayaCandidateReranker(agent=agent, timeout_seconds=60).rank_payloads(warmup_payloads)
        warmup_ms = (time.perf_counter() - started) * 1000
        if set(ranked) != {"warmup-a", "warmup-b"}:
            raise ValueError("Laya warmup returned inconsistent candidate IDs")
        try:
            laya_version = importlib.metadata.version("laya")
        except importlib.metadata.PackageNotFoundError:
            laya_version = getattr(laya, "__version__", "unknown")
        return None, {
            "name": "laya-multilingual", "repo": LAYA_MODEL_REPO, "revision": LAYA_MODEL_REVISION,
            "package_version": laya_version, "python_version": platform.python_version(),
            "torch_version": torch.__version__, "torch_threads": torch.get_num_threads(),
            "timeout_seconds": LAYA_TIMEOUT_SECONDS,
            "device": "cuda" if torch.cuda.is_available() else "cpu",
            "checkpoint_cached": True, "checkpoint_bytes": checkpoint_bytes,
            "load_ms": round(load_ms, 2), "warmup_ms": round(warmup_ms, 2),
            "rss_before_bytes": rss_before, "rss_after_load_bytes": rss_loaded,
            "rss_after_warmup_bytes": _rss_bytes(),
        }
    except Exception as exc:
        reason = f"Laya preflight failed ({type(exc).__name__}); confirm the optional package and pinned local cache"
        if required:
            sys.exit(f"ERROR: cannot run system L: {reason}")
        return reason, None


def render(results, meta, budgets) -> str:
    keys = [k for k in results if "budgets" in results[k]]
    skipped = {k: v["skipped"] for k, v in results.items() if "skipped" in v}
    rows = [("answer_in_context", "answer text in context"), ("gold_section_recall", "gold-section recall"),
            ("doc_source_accuracy", "document source correct"), ("section_source_accuracy", "section source correct"),
            ("mrr", "MRR of answer item"), ("mean_context_bytes", "mean context bytes"),
            ("median_context_bytes", "median context bytes"),
            ("mean_context_tokens", "mean context token count"),
            ("mean_items", "mean items"), ("gold_mrr_before_rerank", "gold section MRR, fused order"),
            ("gold_mrr_after_rerank", "gold section MRR, after rerank"), ("answers_per_kb", "answers per KB of context"),
            ("gold_recall_per_kb", "gold-section recall per KB"), ("mean_rerank_ms", "rerank latency (ms, mean)"), ("mean_fused_sections", "section candidates after filtering"),
            ("mean_system1_rerank_ms", "System 1 rerank latency (ms, mean, docs + chat)"),
            ("system1_inference_calls", "System 1 shortlist inference calls"),
            ("mean_system1_inference_ms", "System 1 latency per shortlist inference (ms)"),
            ("system1_inference_failures", "System 1 inference failures; baseline fallback used"),
            ("system1_timeouts", "System 1 timeouts"),
            ("system1_input_skips", "System 1 oversized/truncated input skips"),
            ("mean_selected_sections", "sections in final context"), ("unrelated_item_rate", "unrelated item rate"),
            ("answer_share_of_context", "answer-bearing share of context"),
            ("queries_with_budget_exclusions", "queries dropping a record for budget"),
            ("mean_total_latency_ms", "mean total latency (ms)"),
            ("p50_total_latency_ms", "p50 total latency (ms)"),
            ("p95_total_latency_ms", "p95 total latency (ms)"),
            ("p95_system1_query_ms", "p95 total System 1 time per query (ms)"),
            ("mean_local_latency_ms", "mean local latency (ms)"),
            ("chat_recall", f"chat recall ({meta['chat_queries']} queries)"), ("fallback_rate", "fallback frequency"),
            ("mean_strategies_run", "mean strategies run per query"), ("pageindex_routed", "navigation calls"),
            ("pageindex_failures", "navigation failures"), ("pageindex_timeouts", "navigation timeouts"),
            ("model_latency_ms_mean", "model latency mean (ms, observed)"),
            ("model_latency_ms_p95", "model latency p95 (ms, observed)"),
            ("est_prompt_tokens_mean", "prompt tokens per call (ESTIMATE, chars/4)"),
            ("observed_prompt_tokens", "prompt tokens total (observed)"),
            ("observed_completion_tokens", "completion tokens total (observed)"),
            ("estimated_cost_usd", "cost USD (ESTIMATE from price table)")]
    lines = ["# Evaluation results", "", "```json", json.dumps(meta, indent=2), "```", "",
             "Systems C/D/E are diagnostics, not evidence of LLM performance."]
    for k, why in skipped.items():
        lines.append(f"\n**System {k} skipped:** {why}")
    for budget in budgets:
        lines += ["", f"## Context budget {budget}", "", "| metric | " + " | ".join(results[k]["label"] for k in keys) + " |",
                  "|---|" + "---|" * len(keys)]
        for key, label in rows:
            cells = []
            for k in keys:
                v = results[k]["budgets"][budget].get(key)
                cells.append("-" if v is None else (f"{v:.2f}" if isinstance(v, float) else str(v)))
            if any(c != "-" for c in cells):
                lines.append(f"| {label} | " + " | ".join(cells) + " |")
    comparison = meta.get("comparison_baseline", "S")
    lines += ["", f"## Answers lost / gained relative to {comparison} (same questions)", ""]
    for k in keys:
        lost = results[k].get(f"answers_lost_vs_{comparison}")
        if lost is not None:
            gained = results[k][f"answers_gained_vs_{comparison}"]
            lines.append(f"- {results[k]['label']}: " + "; ".join(
                f"budget {b}: lost {len(lost[b])}, gained {len(gained[b])}" + (f" (lost: {', '.join(lost[b])})" if lost[b] else "")
                for b in lost))
    lines += ["", "## Indexing", ""] + [
        f"- {results[k]['label']}: {results[k]['index_seconds']} s, {results[k]['records_indexed']} records" for k in keys]
    runtime = results.get("J", {}).get("system1_runtime")
    if runtime:
        delta = None
        if runtime.get("rss_before_bytes") is not None and runtime.get("rss_after_bytes") is not None:
            delta = runtime["rss_after_bytes"] - runtime["rss_before_bytes"]
        summary = (f"- Julia-1 revision `{runtime['revision']}`; checkpoint `{runtime['weights_sha256']}`; "
                   f"load {runtime['load_ms']:.1f} ms; warmup {runtime['warmup_ms']:.1f} ms; "
                   f"checkpoint {runtime['weights_file_bytes'] / (1024 ** 2):.1f} MiB")
        if delta is not None:
            summary += f"; RSS change during load/warmup {delta / (1024 ** 2):+.1f} MiB"
        lines += ["", "## System 1 local resource snapshot", "", summary + "."]
    laya_runtime = results.get("L", {}).get("system1_runtime")
    if laya_runtime:
        load_delta = None
        if laya_runtime.get("rss_before_bytes") is not None and laya_runtime.get("rss_after_load_bytes") is not None:
            load_delta = laya_runtime["rss_after_load_bytes"] - laya_runtime["rss_before_bytes"]
        warm_delta = None
        if laya_runtime.get("rss_after_load_bytes") is not None and laya_runtime.get("rss_after_warmup_bytes") is not None:
            warm_delta = laya_runtime["rss_after_warmup_bytes"] - laya_runtime["rss_after_load_bytes"]
        summary = (f"- Laya `{laya_runtime['repo']}` revision `{laya_runtime['revision']}`; "
                   f"package {laya_runtime['package_version']}, {laya_runtime['torch_version']}, "
                   f"{laya_runtime['device']}; load {laya_runtime['load_ms']:.1f} ms; "
                   f"warmup {laya_runtime['warmup_ms']:.1f} ms; checkpoint "
                   f"{laya_runtime['checkpoint_bytes'] / (1024 ** 2):.1f} MiB")
        if load_delta is not None:
            summary += f"; RSS change on load {load_delta / (1024 ** 2):+.1f} MiB"
        if warm_delta is not None:
            summary += f"; RSS change on warmup {warm_delta / (1024 ** 2):+.1f} MiB"
        lines += ["", "## Laya local resource snapshot", "", summary + "."]
    reference = meta.get("historical_julia_reference")
    if reference:
        historical = reference["systems"]
        lines += ["", "## Saved Julia-1 reference", "",
                  "The table below is the previously recorded H/J run, not a fresh Julia rerun. "
                  "Dataset and corpus hashes were checked against this run.", "",
                  "| budget | saved H answer rate | saved J answer rate | saved H MRR | saved J MRR | "
                  "saved H latency (ms) | saved J latency (ms) |",
                  "|---:|---:|---:|---:|---:|---:|---:|"]
        for budget in budgets:
            h = historical["H"]["budgets"][str(budget)]
            j = historical["J"]["budgets"][str(budget)]
            lines.append(
                f"| {budget} | {h['answer_in_context']:.3f} | {j['answer_in_context']:.3f} | "
                f"{h['mrr']:.3f} | {j['mrr']:.3f} | {h['mean_total_latency_ms']:.1f} | "
                f"{j['mean_total_latency_ms']:.1f} |"
            )
    return "\n".join(lines) + "\n"


def load_historical_julia_reference(dataset: str, current_dataset_hash: str, current_corpus_hash: str,
                                    budgets: tuple[int, ...]):
    result_path = HERE / "system1_results" / dataset / "results.json"
    if not result_path.exists():
        raise FileNotFoundError(f"saved Julia reference is missing for {dataset}")
    saved = json.loads(result_path.read_text(encoding="utf-8"))
    old_meta = saved.get("meta", {})
    if old_meta.get("dataset_sha256") != current_dataset_hash:
        raise ValueError(f"frozen {dataset} question hash differs from the saved Julia run")
    if old_meta.get("corpus_sha256") != current_corpus_hash:
        raise ValueError("frozen corpus hash differs from the saved Julia run")
    if tuple(old_meta.get("budgets", ())) != budgets:
        raise ValueError("evaluation budgets differ from the saved Julia run")
    if not all(key in saved.get("systems", {}) for key in ("H", "J")):
        raise ValueError("saved Julia run is missing H or J results")
    summary_fields = ("answer_in_context", "mrr", "mean_total_latency_ms", "mean_system1_inference_ms",
                      "system1_inference_failures")
    return {
        "source": str(result_path.relative_to(HERE.parent)), "verified_hashes": True,
        "dataset_sha256": old_meta["dataset_sha256"], "corpus_sha256": old_meta["corpus_sha256"],
        "git_sha": old_meta.get("git_sha"), "python": old_meta.get("python"),
        "system1_runtime": old_meta.get("system1_runtime"),
        "systems": {
            key: {
                "label": saved["systems"][key]["label"],
                "budgets": {
                    str(budget): {field: saved["systems"][key]["budgets"][str(budget)].get(field)
                                  for field in summary_fields}
                    for budget in budgets
                },
            }
            for key in ("H", "J")
        },
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--systems", default=None, help="comma list (default A,B,F,C,D,E,N)")
    ap.add_argument("--budgets", default=",".join(map(str, DEFAULT_BUDGETS)))
    ap.add_argument("--model", default=os.environ.get("CELESTIN_PAGEINDEX_MODEL"))
    ap.add_argument("--system1-model-path", default=os.environ.get("CELESTIN_SYSTEM1_MODEL_PATH"),
                    help="local Julia-1 checkout containing the pinned checkpoint")
    ap.add_argument("--f-sweep", action="store_true", help="evaluate selectivity variants of system F")
    ap.add_argument("--require-llm", action="store_true", help="fail instead of skipping N when no model/credentials")
    ap.add_argument("--fts-relax", choices=["on", "off"], default="on",
                    help="bounded FTS5 query relaxation (product default on; off reproduces the first evaluation)")
    ap.add_argument("--dataset", choices=["dev", "heldout", "rerank_challenge"], default="dev",
                    help="question set; rerank_challenge is new and must remain untuned")
    ap.add_argument("--repeats", type=int, default=1,
                    help="number of measured full passes per system after any model preflight warm-up")
    ap.add_argument("--rerank-sweep", action="store_true", help="evaluate section reranking variants of S")
    ap.add_argument("--noise-sweep", action="store_true", help="evaluate relevance-filtering variants of S")
    ap.add_argument("--out", default=str(HERE), help="directory for results.md / results.json")
    args = ap.parse_args(argv)
    if args.repeats < 1:
        ap.error("--repeats must be at least 1")
    global FTS_RELAX
    FTS_RELAX = args.fts_relax == "on"
    use_dataset(args.dataset)
    budgets = tuple(int(b) for b in args.budgets.split(","))
    explicit = args.systems is not None
    keys = RERANK_SWEEP if args.rerank_sweep and not explicit else NOISE_SWEEP if args.noise_sweep and not explicit else SWEEP if args.f_sweep and not explicit else (args.systems or "A,B,F,H,S,C,D,E,Sd,N,SN").split(",")
    unknown = [k for k in keys if k not in SPECS]
    if unknown:
        sys.exit(f"ERROR: unknown systems {unknown}; choose from {sorted(SPECS)}")
    current_dataset_hash = dataset_hash()
    current_corpus_hash = corpus_hash()
    historical_julia = None
    if "L" in keys:
        try:
            historical_julia = load_historical_julia_reference(
                args.dataset, current_dataset_hash, current_corpus_hash, budgets
            )
        except (FileNotFoundError, ValueError) as exc:
            sys.exit(f"ERROR: cannot compare Laya against the saved Julia run: {exc}")
    results: dict = {}
    system1_runtimes = {}
    if "J" in keys:
        reason, system1_runtimes["J"] = check_system1(args.system1_model_path, required=explicit)
        if reason:
            results["J"] = {"skipped": reason}
            keys = [k for k in keys if k != "J"]
    llm_keys = [k for k in keys if SPECS[k].navigator == "llm"]
    if llm_keys:
        reason = check_llm(args.model, required=args.require_llm or (explicit and bool(set(llm_keys) & set(args.systems.split(",")))))
        if reason:
            for k in llm_keys:
                results[k] = {"skipped": reason}
            keys = [k for k in keys if k not in llm_keys]
        else:
            calls = len(budgets) * len(DOC_QUERIES)
            print(f"NOTE: system N will make up to {calls} model calls to {args.model} (outlines and questions "
                  "are sent to the provider; this costs money).", file=sys.stderr)
    sections = {}
    for d in DOCS:
        for s in build_sections(read_doc(d), Path(d).stem):
            sections[(d, s.node_id)] = s
    for key in keys:
        try:
            if key == "L" and "L" not in system1_runtimes:
                reason, system1_runtimes["L"] = check_laya(required=explicit)
                if reason:
                    results["L"] = {"skipped": reason}
                    continue
            results[key] = run_system(
                SPECS[key], sections, budgets, args.model, args.system1_model_path,
                repeats=args.repeats, system1_runtime=system1_runtimes.get(key),
            )
        except Exception as exc:  # recorded, never hidden
            results[key] = {"skipped": f"{type(exc).__name__}: {exc}"}
    base = results.get("S")
    if base and "budgets" in base:
        for key, res in results.items():
            if "budgets" not in res or key == "S":
                continue
            res["answers_lost_vs_S"] = {
                str(b): sorted({q["query"] for q, r in zip(base["queries"][b], res["queries"][b])
                                if q["answered"] and not r["answered"]})
                for b in base["queries"]
            }
            res["answers_gained_vs_S"] = {
                str(b): sorted({q["query"] for q, r in zip(base["queries"][b], res["queries"][b])
                                if r["answered"] and not q["answered"]})
                for b in base["queries"]
            }
            res["chat_answers_lost_vs_S"] = {
                str(b): sorted({q["query"] for q, r in zip(base["chat_queries"][b], res["chat_queries"][b])
                                if q["answered"] and not r["answered"]})
                for b in base["chat_queries"]
            }
    comparison_baseline = "H" if any(key in results and "budgets" in results.get("H", {})
                                     for key in ("J", "L")) else "S"
    comparison = results.get(comparison_baseline)
    if comparison and "budgets" in comparison:
        for key, res in results.items():
            if "budgets" not in res or key == comparison_baseline:
                continue
            res[f"answers_lost_vs_{comparison_baseline}"] = {
                str(b): sorted({q["query"] for q, r in zip(comparison["queries"][b], res["queries"][b])
                                if q["answered"] and not r["answered"]})
                for b in comparison["queries"]
            }
            res[f"answers_gained_vs_{comparison_baseline}"] = {
                str(b): sorted({q["query"] for q, r in zip(comparison["queries"][b], res["queries"][b])
                                if r["answered"] and not q["answered"]})
                for b in comparison["queries"]
            }
            res[f"chat_answers_lost_vs_{comparison_baseline}"] = {
                str(b): sorted({q["query"] for q, r in zip(comparison["chat_queries"][b], res["chat_queries"][b])
                                if q["answered"] and not r["answered"]})
                for b in comparison["chat_queries"]
            }
    try:
        import pageindex
        pi_version = getattr(pageindex, "__version__", None) or __import__("importlib.metadata").metadata.version("pageindex")
    except Exception:
        pi_version = None
    from orbit.semantic.config import load_settings
    sem = load_settings()
    meta = {
        "dataset": args.dataset, "dataset_version": DATASET_VERSION if args.dataset == "dev" else
        (_heldout.HELDOUT_VERSION if args.dataset == "heldout" else _challenge.VERSION),
        "dataset_sha256": current_dataset_hash, "corpus_sha256": current_corpus_hash, "git_sha": git_sha(),
        "working_tree_dirty": working_tree_dirty(),
        "python": platform.python_version(), "pageindex_version": pi_version,
        "navigation_model": args.model if any("budgets" in results.get(k, {}) for k in ("N", "SN")) else None,
        "embedding_model": sem.model_id, "semantic_min_similarity": sem.min_similarity,
        "fts_relax": FTS_RELAX, "budgets": list(budgets), "max_sections_per_navigation": MAX_SECTIONS,
        "measured_repeats": args.repeats, "warmup_count": 1 if "L" in results and "budgets" in results["L"] else 0,
        "doc_queries": len(DOC_QUERIES), "chat_queries": len(CHAT_QUERIES), "documents": len(DOCS),
        "systems_run": [k for k in results if "budgets" in results[k]],
        "comparison_baseline": comparison_baseline,
        "system1_runtime": system1_runtimes.get("J") or system1_runtimes.get("L"),
        "system1_runtimes": system1_runtimes,
        "historical_julia_reference": historical_julia,
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    suffix = (("_rerank_sweep" if args.rerank_sweep and not explicit else "") + ("_noise_sweep" if args.noise_sweep and not explicit else "") + ("_f_sweep" if args.f_sweep and not explicit else "")
              + ("" if args.dataset == "dev" else f"_{args.dataset}") + ("" if FTS_RELAX else "_strict_fts"))
    (out / f"results{suffix}.json").write_text(json.dumps({"meta": meta, "systems": results}, indent=2, default=str))
    text = render(results, meta, budgets)
    (out / f"results{suffix}.md").write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
