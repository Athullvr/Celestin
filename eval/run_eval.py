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
  N  PageIndex, real LLM navigation + FTS5 + semantic         [real-LLM evidence]
  C  DIAGNOSTIC: PageIndex plumbing with a lexical stand-in navigator, FTS5 only
  D  DIAGNOSTIC: as C plus semantic
  E  DIAGNOSTIC: oracle navigator told the answer (upper bound, not achievable)
C, D and E are NOT evidence of LLM performance. Chat memories are ingested in every system.
Corpus: eval/corpus (frozen). Questions: eval/dataset.py (frozen, hashed into the results).
"""

from __future__ import annotations

import argparse
import hashlib
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

HERE = Path(__file__).parent
CORPUS = HERE / "corpus"
PROJECT = "eval"
MAX_SECTIONS = 3
DEFAULT_BUDGETS = (2_000, 20_000)


@dataclass(frozen=True)
class Spec:
    key: str
    label: str
    kind: str  # baseline | real_llm | diagnostic
    docs: str  # whole | sections | tree
    semantic: bool = False
    navigator: str = "none"  # none | standin | oracle | llm
    candidate_limit: int = 100
    margin: float | None = None


SPECS = {s.key: s for s in [
    Spec("A", "A original: docs as messages, FTS5", "baseline", "whole"),
    Spec("B", "B A + semantic", "baseline", "whole", semantic=True),
    Spec("F", "F sections as messages + semantic (no PageIndex)", "baseline", "sections", semantic=True),
    Spec("N", "N PageIndex, REAL LLM + FTS5 + semantic", "real_llm", "tree", semantic=True, navigator="llm"),
    Spec("C", "C diagnostic: stand-in navigator + FTS5", "diagnostic", "tree", navigator="standin"),
    Spec("D", "D diagnostic: stand-in navigator + semantic", "diagnostic", "tree", semantic=True, navigator="standin"),
    Spec("E", "E diagnostic: oracle navigator (upper bound)", "diagnostic", "tree", navigator="oracle"),
]}
for k, margin in (("3", None), ("5", None), ("10", None)):
    SPECS[f"F@{k}"] = Spec(f"F@{k}", f"F with candidate_limit={k}", "baseline", "sections", semantic=True,
                           candidate_limit=int(k))
for m in (0.04, 0.08, 0.12):
    SPECS[f"F~{m}"] = Spec(f"F~{m}", f"F with relative margin {m}", "baseline", "sections", semantic=True, margin=m)
SWEEP = ["F", "F@10", "F@5", "F@3", "F~0.12", "F~0.08", "F~0.04"]


def read_doc(name: str) -> str:
    return (CORPUS / name).read_text()


def dataset_hash() -> str:
    payload = json.dumps([DATASET_VERSION, DOCS, DOC_QUERIES, CHAT_MESSAGES, CHAT_QUERIES], sort_keys=True)
    corpus = "".join(hashlib.sha256(read_doc(d).encode()).hexdigest() for d in DOCS)
    return hashlib.sha256((payload + corpus).encode()).hexdigest()


def git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              cwd=HERE, check=True).stdout.strip()
    except Exception:
        return "unknown"


def semantic_for(db_dir: Path, conn, spec: Spec):
    from orbit.semantic.config import get_provider, load_settings
    from orbit.semantic.indexer import Indexer
    from orbit.semantic.search import SemanticSearch
    from orbit.semantic.vector_index import VectorIndex

    settings = load_settings(db_dir / "main.db")
    provider = get_provider(settings)
    with VectorIndex(db_dir / "v.db", model_id=provider.model_id, dimension=provider.dimension) as index:
        report = Indexer(conn, provider, index).sync()
    return SemanticSearch(provider, db_dir / "v.db", settings.min_similarity, relative_margin=spec.margin), report


def build_system(spec: Spec, tmp: Path, model: str | None, sections_by_key: dict):
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
        if spec.navigator == "llm":
            llm = litellm_chat(model, timeout=60.0)
            navigator = LLMTreeNavigator(llm)
        elif spec.navigator == "oracle":
            navigator = OracleNavigator(sections_by_key)
        else:
            navigator = StandInNavigator()
        backend = PageIndexBackend(tmp / "docs.db", navigator, max_sections=MAX_SECTIONS, cache_size=0)
        records += len(sections_by_key)
    semantic = None
    if spec.semantic:
        semantic, _ = semantic_for(tmp, conn, spec)
    index_secs = time.perf_counter() - t0
    service = RetrievalService(conn, semantic=semantic, documents=backend, candidate_limit=spec.candidate_limit)
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
    return {
        "answered": bool(answering), "doc_ok": doc_ok, "sec_ok": sec_ok,
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
    }


def aggregate(rows, chat_hits, model):
    n = len(rows)
    mean = lambda key: statistics.mean(r[key] for r in rows)
    routed = [r for r in rows if r["pageindex"] == "used"]
    observed = [r["usage"] for r in routed if r["usage"]]
    out = {
        "answer_in_context": mean("answered"), "doc_source_accuracy": mean("doc_ok"),
        "section_source_accuracy": mean("sec_ok"), "gold_section_recall": mean("gold_recall"), "mrr": mean("rr"),
        "mean_context_bytes": mean("tokens"), "mean_items": mean("items"),
        "unrelated_item_rate": mean("unrelated_item_rate"), "answer_share_of_context": mean("density"),
        "queries_with_budget_exclusions": sum(r["budget_excluded"] > 0 for r in rows),
        "mean_total_latency_ms": mean("total_ms"),
        "mean_local_latency_ms": statistics.mean(r["total_ms"] - r["model_ms"] for r in rows),
        "chat_recall": sum(chat_hits) / len(chat_hits),
        "pageindex_routed": len(routed), "pageindex_skipped": sum(r["pageindex"] == "skipped" for r in rows),
        "pageindex_failures": sum(r["pageindex_failed"] for r in rows),
        "pageindex_timeouts": sum(r["pageindex_timeout"] for r in rows),
        "queries": n,
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


def run_system(spec, sections, budgets, model):
    with tempfile.TemporaryDirectory() as t:
        service, ids, index_secs, navigator, records = build_system(spec, Path(t), model, sections)
        out = {"label": spec.label, "kind": spec.kind, "index_seconds": round(index_secs, 2),
               "records_indexed": records, "budgets": {}, "queries": {}}
        for budget in budgets:
            rows = [run_query(service, q, budget, ev, gd, ids, sections, navigator) for q, ev, gd in DOC_QUERIES]
            chat = []
            for query, evidence in CHAT_QUERIES:
                bundle = service.retrieve_context(PROJECT, query, budget)
                chat.append(any(evidence.lower() in i.content.lower() for i in bundle.items if i.record_kind == "chat_message"))
            out["budgets"][budget] = aggregate(rows, chat, model)
            out["queries"][budget] = [{"query": q[0], **r} for q, r in zip(DOC_QUERIES, rows)]
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


def render(results, meta, budgets) -> str:
    keys = [k for k in results if "budgets" in results[k]]
    skipped = {k: v["skipped"] for k, v in results.items() if "skipped" in v}
    rows = [("answer_in_context", "answer text in context"), ("gold_section_recall", "gold-section recall"),
            ("doc_source_accuracy", "document source correct"), ("section_source_accuracy", "section source correct"),
            ("mrr", "MRR of answer item"), ("mean_context_bytes", "mean context bytes"),
            ("mean_items", "mean items"), ("unrelated_item_rate", "unrelated item rate"),
            ("answer_share_of_context", "answer-bearing share of context"),
            ("queries_with_budget_exclusions", "queries dropping a record for budget"),
            ("mean_total_latency_ms", "mean total latency (ms)"), ("mean_local_latency_ms", "mean local latency (ms)"),
            ("chat_recall", "chat recall (5 queries)"), ("pageindex_routed", "navigation calls"),
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
    lines += ["", "## Indexing", ""] + [
        f"- {results[k]['label']}: {results[k]['index_seconds']} s, {results[k]['records_indexed']} records" for k in keys]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--systems", default=None, help="comma list (default A,B,F,C,D,E,N)")
    ap.add_argument("--budgets", default=",".join(map(str, DEFAULT_BUDGETS)))
    ap.add_argument("--model", default=os.environ.get("CELESTIN_PAGEINDEX_MODEL"))
    ap.add_argument("--f-sweep", action="store_true", help="evaluate selectivity variants of system F")
    ap.add_argument("--require-llm", action="store_true", help="fail instead of skipping N when no model/credentials")
    ap.add_argument("--out", default=str(HERE), help="directory for results.md / results.json")
    args = ap.parse_args(argv)
    budgets = tuple(int(b) for b in args.budgets.split(","))
    explicit = args.systems is not None
    keys = SWEEP if args.f_sweep and not explicit else (args.systems or "A,B,F,C,D,E,N").split(",")
    unknown = [k for k in keys if k not in SPECS]
    if unknown:
        sys.exit(f"ERROR: unknown systems {unknown}; choose from {sorted(SPECS)}")
    results: dict = {}
    if "N" in keys:
        reason = check_llm(args.model, required=args.require_llm or (explicit and "N" in args.systems.split(",")))
        if reason:
            results["N"] = {"skipped": reason}
            keys = [k for k in keys if k != "N"]
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
            results[key] = run_system(SPECS[key], sections, budgets, args.model)
        except Exception as exc:  # recorded, never hidden
            results[key] = {"skipped": f"{type(exc).__name__}: {exc}"}
    try:
        import pageindex
        pi_version = getattr(pageindex, "__version__", None) or __import__("importlib.metadata").metadata.version("pageindex")
    except Exception:
        pi_version = None
    from orbit.semantic.config import load_settings
    sem = load_settings()
    meta = {
        "dataset_version": DATASET_VERSION, "dataset_sha256": dataset_hash(), "git_sha": git_sha(),
        "python": platform.python_version(), "pageindex_version": pi_version,
        "navigation_model": args.model if "N" in results and "budgets" in results["N"] else None,
        "embedding_model": sem.model_id, "semantic_min_similarity": sem.min_similarity,
        "budgets": list(budgets), "max_sections_per_navigation": MAX_SECTIONS,
        "doc_queries": len(DOC_QUERIES), "chat_queries": len(CHAT_QUERIES), "documents": len(DOCS),
        "systems_run": [k for k in results if "budgets" in results[k]],
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    suffix = "_f_sweep" if args.f_sweep and not explicit else ""
    (out / f"results{suffix}.json").write_text(json.dumps({"meta": meta, "systems": results}, indent=2, default=str))
    text = render(results, meta, budgets)
    (out / f"results{suffix}.md").write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
