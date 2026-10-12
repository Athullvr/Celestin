"""Deterministic policy deciding whether a query is worth a PageIndex navigation call.

Navigation costs a model round trip and thousands of prompt tokens, so it is
skipped when the query is an identifier lookup, too short to be a question,
when the budget is too small to hold a section, when the outline would be too
large, or when a cheap strict full-term FTS5 hit on an approved decision already
answers it. No model call is used to decide.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MIN_WORDS = 3
MIN_BUDGET = 500
MAX_OUTLINE_TOKENS = 40_000

_WORD = re.compile(r"\w+", re.UNICODE)
_MIXED_ALNUM = re.compile(r"(?=\w*[A-Za-z])(?=\w*\d)\w+")
_FILE_OR_PATH = re.compile(r"\w[\w\-]*\.[A-Za-z]{1,5}\b|[\w\-.]+[/\\][\w\-.]+")
_VERSION = re.compile(r"\bv?\d+(\.\d+){1,}\b")


def has_identifier(query: str) -> bool:
    """True for error codes, snake_case names, mixed letter-digit tokens, versions, filenames and paths."""
    return bool(
        "_" in query
        or _MIXED_ALNUM.search(query)
        or _FILE_OR_PATH.search(query)
        or _VERSION.search(query)
    )


@dataclass(frozen=True, slots=True)
class RouteDecision:
    use: bool
    reason: str


def decide_route(
    query: str,
    *,
    token_budget: int,
    approved_strict_hit: bool = False,
    outline_tokens: int | None = None,
    min_words: int = MIN_WORDS,
    min_budget: int = MIN_BUDGET,
    max_outline_tokens: int = MAX_OUTLINE_TOKENS,
) -> RouteDecision:
    if has_identifier(query):
        return RouteDecision(False, "identifier or filename lookup")
    if len(_WORD.findall(query)) < min_words:
        return RouteDecision(False, f"query has fewer than {min_words} words")
    if token_budget < min_budget:
        return RouteDecision(False, f"budget below {min_budget}")
    if outline_tokens is not None and outline_tokens > max_outline_tokens:
        return RouteDecision(False, f"outline too large (~{outline_tokens} tokens)")
    if approved_strict_hit:
        return RouteDecision(False, "approved decision already matches all query terms")
    return RouteDecision(True, "natural-language question with indexed documents")
