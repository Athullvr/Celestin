"""Deterministic retrieval strategy selector.

Picks one primary strategy (and at most one fallback) from the strategies that are actually
available, using only the query text, the available backends, whether documents are indexed, the
budget and the estimated navigation cost. No model call is made to decide. The rules are initial
heuristics, not proven optimal thresholds; the evaluation in eval/ measures their effect.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from orbit.pageindex.routing import decide_route, has_identifier

STRATEGY_NAMES = ("fts", "semantic", "sections", "pageindex")
MAX_STRATEGIES = 2  # primary plus at most one fallback

_WORD = re.compile(r"\w+", re.UNICODE)
_QUOTED = re.compile(r'"[^"]+"')
_ERROR_CUE = re.compile(r"\b(error|exception|traceback|stack ?trace|failed with|errno|segfault)\b", re.I)
_DOC_CUE = re.compile(
    r"\b(docs?|documentation|readme|spec|specification|design|architecture|guide|section|chapter|manual|"
    r"install|installation|configure|configuration|setup|contract|schema|policy|requirements?|"
    r"limitations?|reference|api|documented|according to)\b", re.I)
_MULTI_CUE = re.compile(
    r"\b(across|compare|comparison|summari[sz]e|overview|end to end|end-to-end|relationship|all of|"
    r"every|list all|walk ?through|trade-?offs?|differences?)\b", re.I)
_DISCUSSION_CUE = re.compile(
    r"\b(we discussed|did we|we decided|we chose|decided|earlier|previous(ly)?|last time|remember|recall|"
    r"before|our discussion|we agreed|agreed)\b", re.I)
_QUESTION_START = re.compile(r"^\s*(why|how|what|which|who|when|where|can|does|do|is|are|should|explain)\b", re.I)


@dataclass(frozen=True, slots=True)
class SelectorContext:
    available: frozenset[str]
    has_documents: bool
    token_budget: int
    est_navigation_tokens: int | None = None


@dataclass(frozen=True, slots=True)
class Plan:
    primary: str
    fallback: str | None
    reason: str
    features: tuple[str, ...] = ()

    @property
    def strategies(self) -> tuple[str, ...]:
        return (self.primary,) if self.fallback is None else (self.primary, self.fallback)

    def as_dict(self) -> dict:
        return {"primary": self.primary, "fallback": self.fallback, "reason": self.reason,
                "features": list(self.features)}


def classify(query: str) -> tuple[str, ...]:
    features = []
    if has_identifier(query) or _QUOTED.search(query) or _ERROR_CUE.search(query):
        features.append("identifier")
    if _DOC_CUE.search(query):
        features.append("doc_intent")
    if _MULTI_CUE.search(query):
        features.append("multi_section")
    if _DISCUSSION_CUE.search(query):
        features.append("discussion")
    words = len(_WORD.findall(query))
    if _QUESTION_START.search(query) or words >= 5:
        features.append("question")
    if words < 3:
        features.append("short")
    return tuple(features)


def _navigation_ok(query: str, ctx: SelectorContext) -> bool:
    if "pageindex" not in ctx.available or not ctx.has_documents:
        return False
    return decide_route(query, token_budget=ctx.token_budget, outline_tokens=ctx.est_navigation_tokens).use


def validate_plan(plan: Plan, ctx: SelectorContext) -> Plan:
    """Drop anything unavailable or duplicated; always end with a runnable plan of at most two strategies."""
    primary = plan.primary if plan.primary in ctx.available and plan.primary in STRATEGY_NAMES else "fts"
    fallback = plan.fallback
    if fallback not in ctx.available or fallback not in STRATEGY_NAMES or fallback == primary:
        fallback = None
    if primary in ("sections", "pageindex") and not ctx.has_documents:
        primary = "fts"
        if fallback in ("sections", "pageindex"):
            fallback = None
    if fallback in ("sections", "pageindex") and not ctx.has_documents:
        fallback = None
    changed = (primary, fallback) != (plan.primary, plan.fallback)
    return Plan(primary, fallback, plan.reason + (" (adjusted to available strategies)" if changed else ""),
                plan.features)


def plan_query(query: str, ctx: SelectorContext) -> Plan:
    f = classify(query)
    has = ctx.available
    docs = ctx.has_documents
    semantic = "semantic" in has
    sections = "sections" in has and docs

    def cheapest(*names):
        return next((n for n in names if n in has), None)

    if "identifier" in f or "short" in f:
        plan = Plan("fts", cheapest("sections" if docs else "semantic", "semantic"),
                    "identifier, error message or short lookup: exact keyword match first", f)
    elif "doc_intent" in f and "multi_section" in f and _navigation_ok(query, ctx):
        plan = Plan("pageindex", cheapest("sections", "fts"),
                    "documentation question spanning sections: hierarchical navigation", f)
    elif "discussion" in f:
        plan = Plan("semantic" if semantic else "fts", cheapest("sections" if docs else "fts", "fts"),
                    "question about an earlier discussion or decision: semantic retrieval over memory", f)
    elif sections and ("doc_intent" in f or "question" in f):
        # Indexed documents are the likeliest source of a factual question that does not refer to a
        # past discussion; semantic memory search is the fallback (found by failure analysis of
        # an earlier rule that sent such questions to chat memory first and almost always fell back).
        plan = Plan("sections", "pageindex" if "doc_intent" in f and _navigation_ok(query, ctx)
                    else cheapest("semantic", "fts"),
                    "question with indexed documents: heading-section retrieval", f)
    elif "question" in f and semantic:
        plan = Plan("semantic", "fts", "conceptual question: semantic retrieval", f)
    else:
        plan = Plan("fts", cheapest("semantic", "sections" if docs else "fts"),
                    "default: keyword retrieval", f)
    return validate_plan(plan, ctx)
