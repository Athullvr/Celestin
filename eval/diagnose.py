"""Where does context noise come from? Per-stage trace of retrieval on the frozen corpus.

    python eval/diagnose.py [--system S] [--budget 20000]

Uses RetrievalService.last_diagnostics (counts, ranks, native scores, timings; no content).
An item is "relevant" when it contains the question's gold evidence string (as in run_eval.py).
"""

from __future__ import annotations

import argparse
import statistics
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import run_eval as ev
from orbit.pageindex.tree import build_sections


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--system", default="S")
    ap.add_argument("--budget", type=int, default=20_000)
    args = ap.parse_args()
    sections = {}
    for d in ev.DOCS:
        for s in build_sections(ev.read_doc(d), Path(d).stem):
            sections[(d, s.node_id)] = s
    spec = ev.SPECS[args.system]
    rows = []
    with tempfile.TemporaryDirectory() as t:
        service, ids, _, navigator, _ = ev.build_system(spec, Path(t), None, sections)
        for query, evidence, gold_docs in ev.DOC_QUERIES:
            bundle = service.retrieve_context(ev.PROJECT, query, args.budget)
            diag = service.last_diagnostics
            for rank, sel in enumerate(diag["selected"], start=1):
                item = next(i for i in bundle.items if i.record_id == sel["record_id"])
                rows.append({"q": query, "rank": rank, "n_items": len(diag["selected"]), "type": sel["type"],
                             "bytes": sel["bytes"], "relevant": evidence.lower() in item.content.lower(),
                             "methods": tuple(sorted(sel["methods"])), "info": sel["methods"], "diag": diag})
    sec = [r for r in rows if r["type"] == "document_section"]
    print(f"system {args.system}, budget {args.budget}: {len(rows)} selected items over {len(ev.DOC_QUERIES)} queries "
          f"({len(sec)} sections)")
    d0 = [r["diag"] for r in {r["q"]: r for r in rows}.values()]
    print("\nmean candidates per query (before budget):")
    for t in ("chat_message", "canonical_decision", "document_section"):
        print(f"  fused {t}: {statistics.mean(d['fused'].get(t, 0) for d in d0):.1f}")
    for name in ("fts", "semantic", "sections"):
        counts = Counter()
        for d in d0:
            for m, n in d["strategies"].get(name, {}).get("candidates", {}).items():
                counts[m] += n
        for m, n in counts.items():
            print(f"  {name}/{m}: {n / len(d0):.1f}")
    print("\nirrelevant share by item type:")
    for t in ("chat_message", "document_section"):
        grp = [r for r in rows if r["type"] == t]
        if grp:
            print(f"  {t}: {sum(not r['relevant'] for r in grp)}/{len(grp)} irrelevant")
    print("\nsection items by the retrieval methods that found them (irrelevant / total):")
    for m, n in sorted(Counter(r["methods"] for r in sec).items(), key=lambda kv: -kv[1]):
        bad = sum(1 for r in sec if r["methods"] == m and not r["relevant"])
        print(f"  {'+'.join(m)}: {bad}/{n}")
    print("\nsection items by position in the final context (irrelevant / total):")
    for lo, hi in ((1, 1), (2, 3), (4, 6), (7, 99)):
        grp = [r for r in sec if lo <= r["rank"] <= hi]
        if grp:
            print(f"  position {lo}-{hi if hi < 99 else '+'}: {sum(not r['relevant'] for r in grp)}/{len(grp)}")
    print("\nsemantic similarity of sections (relevant vs irrelevant):")
    for rel in (True, False):
        sims = [r["info"]["sections_semantic"]["score"] for r in sec
                if r["relevant"] == rel and "sections_semantic" in r["info"]]
        if sims:
            print(f"  {'relevant' if rel else 'irrelevant'}: n={len(sims)} min={min(sims):.2f} "
                  f"median={statistics.median(sims):.2f} max={max(sims):.2f}")
    fts_only = [r for r in sec if r["methods"] == ("sections_fts",)]
    print(f"\nsections found only by keyword search (relaxed OR tier): {len(fts_only)}, irrelevant "
          f"{sum(not r['relevant'] for r in fts_only)}")
    sizes = [r["bytes"] for r in sec]
    big = [r for r in sec if r["bytes"] >= 2000]
    print(f"\nsection bytes: median {statistics.median(sizes):.0f}, max {max(sizes)}; "
          f"{len(big)} sections >= 2000 bytes ({sum(r['bytes'] for r in big)} of {sum(sizes)} section bytes), "
          f"{sum(not r['relevant'] for r in big)} of them irrelevant")
    fills = [d["context_bytes"] / args.budget for d in d0]
    print(f"context fill ratio: mean {statistics.mean(fills):.2f}; excluded for budget per query: "
          f"{statistics.mean(d['excluded'].get('token_budget', 0) for d in d0):.1f}, duplicates "
          f"{statistics.mean(d['excluded'].get('duplicate_content', 0) for d in d0):.2f}")
    print("stage latency ms (mean): " + ", ".join(
        f"{k} {statistics.mean(d['stage_ms'][k] for d in d0):.1f}" for k in ("strategies", "fusion", "build")))


if __name__ == "__main__":
    main()
