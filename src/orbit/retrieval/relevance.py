"""Section relevance helpers: relative-margin filtering, top-K capping and query-focused excerpts.

All functions are pure and deterministic. Nothing here compares scores from different retrieval
methods; each filter works on one method's own scores or on the fused rank order.
"""

from __future__ import annotations

import re
from typing import Sequence

from orbit.retrieval.fts import _STOPWORDS, _WORD
from orbit.semantic.margin import margin_keep  # noqa: F401  (re-exported)

EXCERPT_MARKER = "[...]"


def top_k_with_exemptions(ordered_ids: Sequence[str], k: int | None, exempt: set[str]) -> set[str]:
    """Ids kept by a rank cap: the first ``k`` of a best-first list plus every exempt id."""
    if k is None:
        return set(ordered_ids)
    return set(ordered_ids[:k]) | (exempt & set(ordered_ids))


def _blocks(lines: list[str]) -> list[tuple[int, int]]:
    """(start, end) line indexes of paragraphs; blank lines inside code fences do not split."""
    blocks, start, in_fence = [], None, False
    for i, line in enumerate(lines):
        if line.strip().startswith("```"):
            in_fence = not in_fence
        if line.strip() == "" and not in_fence:
            if start is not None:
                blocks.append((start, i - 1))
                start = None
        elif start is None:
            start = i
    if start is not None:
        blocks.append((start, len(lines) - 1))
    return blocks


def _terms(text: str) -> set[str]:
    return {w.casefold() for w in _WORD.findall(text) if w.casefold() not in _STOPWORDS and len(w) > 2}


def excerpt_section(
    text: str, first_line: int, query: str, max_bytes: int | None
) -> tuple[str, list[tuple[int, int]] | None]:
    """Query-focused excerpt of a long section, or the full text when it already fits.

    Keeps the heading block and the paragraphs that share the most terms with ``query`` (ties: earlier
    first) until ``max_bytes`` is reached, in original order, joined by ``[...]``. At least one body
    paragraph is kept; with no term overlap the first paragraphs are used. Returns the text and the
    ORIGINAL document line ranges (1-based, inclusive) that were kept, or ``None`` when the section
    is returned whole. Source text is never altered inside a kept paragraph.
    """
    if max_bytes is None or len(text.encode("utf-8")) <= max_bytes:
        return text, None
    lines = text.split("\n")
    blocks = _blocks(lines)
    if len(blocks) < 2:
        return text, None
    query_terms = _terms(query)
    heading, body = blocks[0], blocks[1:]
    size = lambda b: len("\n".join(lines[b[0]: b[1] + 1]).encode("utf-8"))
    scored = sorted(
        range(len(body)),
        key=lambda i: (-len(query_terms & _terms("\n".join(lines[body[i][0]: body[i][1] + 1]))), i),
    )
    chosen: list[int] = []
    used = size(heading)
    for i in scored:
        has_overlap = bool(query_terms & _terms("\n".join(lines[body[i][0]: body[i][1] + 1])))
        if chosen and (not has_overlap or used + size(body[i]) > max_bytes):
            continue
        chosen.append(i)
        used += size(body[i])
    kept = [heading] + [body[i] for i in sorted(chosen)]
    parts, previous_end = [], None
    for start, end in kept:
        if previous_end is not None and start > previous_end + 1:
            parts.append(EXCERPT_MARKER)
        parts.append("\n".join(lines[start: end + 1]))
        previous_end = end
    ranges = [(first_line + s, first_line + e) for s, e in kept]
    return "\n\n".join(parts), ranges
