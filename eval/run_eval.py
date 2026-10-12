"""Compare the original Celestin pipeline with the PageIndex-integrated one.

    python eval/run_eval.py            # writes eval/results.md and eval/results.json

Systems (all through RetrievalService.retrieve_context on disposable databases):
  A  baseline    each document ingested as ONE chat message (the only way the original
                 pipeline can hold a document); FTS5 only
  B  baseline+sem  same, plus semantic search (real embedding model, needs the cached model)
  C  pageindex   documents tree-indexed; FTS5 + PageIndex sections
  D  full        documents tree-indexed; FTS5 + semantic + PageIndex sections
  F  sections-as-messages  every heading section ingested as its own chat message; FTS5 + semantic
                 (the no-PageIndex alternative: same tree parser, existing retrieval only)
  E  oracle      like C but the navigator is told the answer: an UPPER BOUND for what perfect
                 navigation could return, not an achievable result
Chat memories are ingested as messages in every system.

IMPORTANT: no LLM API key was available when this was written, so C and D navigate with
a deterministic lexical stand-in (eval/standin.py), NOT an LLM. Results show the effect of
section granularity and the plumbing, not the quality of LLM reasoning over the tree.
"""

from __future__ import annotations

import json
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from dataset import CHAT_MESSAGES, CHAT_QUERIES, DOC_QUERIES, DOCS
from standin import OracleNavigator, StandInNavigator

from orbit.database.engine import connect
from orbit.pageindex.backend import PageIndexBackend
from orbit.pageindex.indexer import index_markdown_text
from orbit.pageindex.store import PageIndexStore
from orbit.pageindex.tree import build_sections
from orbit.repositories.messages import ChatMessageRepository
from orbit.retrieval import RetrievalService

ROOT = Path(__file__).resolve().parents[1]
BUDGETS = (2_000, 20_000)
PROJECT = "eval"


def semantic_for(db_dir: Path, conn):
    from orbit.semantic.config import get_provider, load_settings
    from orbit.semantic.indexer import Indexer
    from orbit.semantic.search import SemanticSearch
    from orbit.semantic.vector_index import VectorIndex

    settings = load_settings(db_dir / "main.db")
    provider = get_provider(settings)
    with VectorIndex(db_dir / "v.db", model_id=provider.model_id, dimension=provider.dimension) as index:
        report = Indexer(conn, provider, index).sync()
    return SemanticSearch(provider, db_dir / "v.db", settings.min_similarity), report


def build_system(name: str, tmp: Path):
    conn = connect(tmp / "main.db")
    messages = ChatMessageRepository(conn)
    texts = {d: (ROOT / d).read_text() for d in DOCS}
    ids: dict[str, tuple[str, str | None]] = {}  # message id -> (document, section node) source mapping
    for text in CHAT_MESSAGES:
        messages.insert(PROJECT, "chat", "user", text)
    t0 = time.perf_counter()
    docs_backend = None
    navigator = None
    if name in ("A", "B"):
        for d, text in texts.items():
            ids[str(messages.insert(PROJECT, "docs", "user", text))] = (d, None)
    elif name == "F":
        for d, text in texts.items():
            for sec in build_sections(text, Path(d).stem):
                ids[str(messages.insert(PROJECT, d, "user", f"{' > '.join(sec.path)}\n{sec.text}"))] = (d, sec.node_id)
    else:
        with PageIndexStore(tmp / "docs.db") as store:
            for d, text in texts.items():
                index_markdown_text(store, PROJECT, d, text)
        navigator = OracleNavigator(SECTIONS) if name == "E" else StandInNavigator()
        docs_backend = PageIndexBackend(tmp / "docs.db", navigator, max_sections=3)
    semantic = None
    sem_report = None
    if name in ("B", "D", "F"):
        semantic, sem_report = semantic_for(tmp, conn)
    index_secs = time.perf_counter() - t0
    service = RetrievalService(conn, semantic=semantic, documents=docs_backend)
    return service, ids, index_secs, sem_report, navigator


def relevant(item, evidence: str, gold_docs: list[str], ids: dict, sections: dict) -> tuple[bool, bool]:
    """(document-level source correct, section-level source correct) for one context item."""
    if item.record_kind == "document_section":
        doc = item.source_id
        node = item.record_id.rsplit("#", 1)[1]
        sec = sections.get((doc, node))
        return doc in gold_docs, bool(sec and doc in gold_docs and evidence.lower() in sec.text.lower())
    doc, node = ids.get(item.record_id, (None, None))
    sec = sections.get((doc, node)) if node else None
    return doc in gold_docs, bool(sec and doc in gold_docs and evidence.lower() in sec.text.lower())


def run_system(name: str, sections_by_key: dict) -> dict:
    with tempfile.TemporaryDirectory() as t:
        service, ids, index_secs, sem_report, navigator = build_system(name, Path(t))
        out = {"index_seconds": round(index_secs, 2), "budgets": {}}
        for budget in BUDGETS:
            service.retrieve_context(PROJECT, "warm up query", budget)
            rows = []
            for query, evidence, gold_docs in DOC_QUERIES:
                if isinstance(navigator, OracleNavigator):
                    navigator.target = (evidence, gold_docs)
                t0 = time.perf_counter()
                bundle = service.retrieve_context(PROJECT, query, budget)
                latency = (time.perf_counter() - t0) * 1000
                answered = any(evidence.lower() in i.content.lower() for i in bundle.items)
                doc_ok = sec_ok = False
                first = None
                for rank, item in enumerate(bundle.items, start=1):
                    d, s = relevant(item, evidence, gold_docs, ids, sections_by_key)
                    doc_ok |= d
                    sec_ok |= s
                    if first is None and evidence.lower() in item.content.lower():
                        first = rank
                gold_bytes = sum(len(i.content.encode()) for i in bundle.items if evidence.lower() in i.content.lower())
                rows.append(dict(answered=answered, doc_ok=doc_ok, sec_ok=sec_ok, rr=1 / first if first else 0.0,
                                 tokens=bundle.token_count, items=len(bundle.items), latency=latency,
                                 budget_excluded=sum(e.reason == "token_budget" for e in bundle.excluded),
                                 density=(gold_bytes / max(1, len(bundle.rendered_context.encode())))))
            chat = []
            for query, evidence in CHAT_QUERIES:
                bundle = service.retrieve_context(PROJECT, query, budget)
                chat.append(any(evidence.lower() in i.content.lower() for i in bundle.items if i.record_kind == "chat_message"))
            n = len(rows)
            out["budgets"][budget] = {
                "doc_answer_recall": sum(r["answered"] for r in rows) / n,
                "doc_source_accuracy": sum(r["doc_ok"] for r in rows) / n,
                "section_source_accuracy": sum(r["sec_ok"] for r in rows) / n,
                "mrr": statistics.mean(r["rr"] for r in rows),
                "mean_context_tokens": statistics.mean(r["tokens"] for r in rows),
                "mean_answer_density": statistics.mean(r["density"] for r in rows),
                "mean_items": statistics.mean(r["items"] for r in rows),
                "queries_with_budget_exclusions": sum(r["budget_excluded"] > 0 for r in rows),
                "mean_latency_ms": statistics.mean(r["latency"] for r in rows),
                "chat_recall": sum(chat) / len(chat),
            }
        if sem_report:
            out["semantic_embedded"] = sem_report.embedded
        return out


SECTIONS: dict = {}


def main() -> None:
    sections = SECTIONS
    for d in DOCS:
        for s in build_sections((ROOT / d).read_text(), Path(d).stem):
            sections[(d, s.node_id)] = s
    results = {}
    for name in "ABFCDE":
        try:
            results[name] = run_system(name, sections)
        except Exception as exc:  # e.g. embedding model not cached/offline
            results[name] = {"error": f"{type(exc).__name__}: {exc}"}
    (Path(__file__).parent / "results.json").write_text(json.dumps(results, indent=2))
    labels = {"A": "A baseline (docs as messages, FTS5)", "B": "B baseline + semantic",
              "C": "C PageIndex tree (stand-in navigator) + FTS5", "D": "D PageIndex + semantic + FTS5",
              "F": "F sections-as-messages + semantic (no PageIndex)", "E": "E oracle navigator (upper bound)"}
    metrics = [("doc_answer_recall", "answer text in context"), ("doc_source_accuracy", "document source correct"),
               ("section_source_accuracy", "section source correct"), ("mrr", "MRR of answer item"),
               ("mean_context_tokens", "mean context size (bytes)"), ("mean_answer_density", "answer-bearing share of context"),
               ("queries_with_budget_exclusions", "queries that dropped a record for budget"),
               ("mean_latency_ms", "mean latency (ms, warm)"), ("chat_recall", "chat-memory recall (5 queries)")]
    lines = [f"# Evaluation results ({len(DOC_QUERIES)} document queries, {len(CHAT_QUERIES)} chat queries, "
             f"{len(DOCS)} documents)\n", "Navigation in C and D is a lexical stand-in, not an LLM; E is an oracle upper bound (see run_eval.py).\n"]
    for budget in BUDGETS:
        lines += [f"\n## Context budget {budget}\n", "| metric | " + " | ".join(labels[k] for k in "ABFCDE") + " |",
                  "|---|" + "---|" * 6]
        for key, label in metrics:
            cells = []
            for k in "ABFCDE":
                r = results[k]
                v = r["budgets"][budget][key] if "budgets" in r else "n/a"
                cells.append(f"{v:.2f}" if isinstance(v, float) else str(v))
            lines.append(f"| {label} | " + " | ".join(cells) + " |")
    lines += ["\n## Indexing cost (seconds, includes embeddings where used)\n"]
    lines += [f"- {labels[k]}: " + (str(results[k].get("index_seconds")) if "index_seconds" in results[k] else results[k]["error"])
              for k in "ABFCDE"]
    (Path(__file__).parent / "results.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
