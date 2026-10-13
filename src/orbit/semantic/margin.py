"""Relative-margin filtering for one retrieval method's scores (no dependencies, so it can be imported anywhere)."""

from __future__ import annotations

from typing import Sequence


def margin_keep(scores: Sequence[float], margin: float | None) -> list[bool]:
    """Which hits survive a relative margin: keep ``score >= best - margin``.

    ``scores`` come from ONE method and must be "higher is better" values on a common scale (cosine
    similarity). Semantics for edge cases: ``margin`` None keeps everything; an empty list returns
    []; a single hit is always kept; ties with the best are all kept; zero or negative scores work
    unchanged because only differences matter; a missing (None) or NaN score is never silently
    dropped by this filter, so unscored evidence is kept rather than lost.
    """
    if margin is None:
        return [True] * len(scores)
    known = [s for s in scores if s is not None and s == s]
    if not known:
        return [True] * len(scores)
    cutoff = max(known) - margin
    return [s is None or s != s or s >= cutoff for s in scores]
