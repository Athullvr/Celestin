"""Deterministic lexical stand-in for LLM navigation (evaluation only, never shipped).

It scores each outline entry by how many query content words appear in the
section path and opening snippet (the same information an LLM would see).
"""

from __future__ import annotations

import re

STOP = set("a an the of to in on for and or is are was were be how what which who why when does do did can may "
           "must by with from that this it as at after before over under between about into than then".split())


def _stem(word: str) -> str:
    return word[:5]


def _terms(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z0-9_]+", text.lower()) if w not in STOP and len(w) > 2}


class StandInNavigator:
    def select(self, query, outline, limit):
        q = _terms(query)
        scored = []
        for order, entry in enumerate(outline):
            overlap = len(q & _terms(" ".join(entry.path) + " " + entry.snippet))
            if overlap:
                scored.append((-overlap, order, entry))
        scored.sort(key=lambda t: t[:2])
        return [(e.doc_key, e.node_id) for _, _, e in scored[:limit]]


class OracleNavigator:
    """Evaluation upper bound: returns sections that actually contain the answer."""

    def __init__(self, sections: dict) -> None:
        self._sections = sections
        self.target: tuple[str, list[str]] = ("", [])

    def select(self, query, outline, limit):
        evidence, docs = self.target
        found = [(d, n) for (d, n), s in self._sections.items() if d in docs and evidence.lower() in s.text.lower()]
        return found[:limit]
