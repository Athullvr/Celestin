"""PageIndex retrieval backend: prepare outline, navigate, return traceable sections."""

from __future__ import annotations

import hashlib
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from .errors import PageIndexUnavailable
from .navigator import OutlineEntry, SNIPPET_CHARS, TreeNavigator
from .routing import RouteDecision, decide_route
from .store import PageIndexStore, StoredSection

DEFAULT_CACHE_SIZE = 64
_CACHE: "OrderedDict[tuple, list[tuple[str, str]]]" = OrderedDict()


def clear_navigation_cache() -> None:
    _CACHE.clear()


def route(query: str) -> str | None:
    """Reason to skip PageIndex for a query on its own text (compatibility helper)."""
    decision = decide_route(query, token_budget=10**9)
    return None if decision.use else decision.reason


@dataclass(frozen=True, slots=True)
class Prepared:
    project: str
    sections: list[StoredSection]
    outline: list[OutlineEntry]
    fingerprint: str
    est_prompt_tokens: int


@dataclass(slots=True)
class NavigationStats:
    """What one navigation did. ``usage`` is provider-reported; ``est_*`` are estimates."""

    outcome: str = "ok"
    elapsed_ms: float = 0.0
    cache_hit: bool = False
    prompt_chars: int = 0
    est_prompt_tokens: int = 0
    usage: dict | None = None

    def as_dict(self) -> dict:
        info = {
            "outcome": self.outcome,
            "elapsed_ms": round(self.elapsed_ms, 1),
            "cache_hit": self.cache_hit,
            "est_prompt_tokens": self.est_prompt_tokens,
        }
        if self.usage:
            info["usage"] = self.usage
        return info


class PageIndexBackend:
    def __init__(
        self,
        store_path: str | Path,
        navigator: TreeNavigator | None,
        *,
        max_sections: int = 5,
        unavailable_reason: str | None = None,
        cache_size: int = 0,
        cache_namespace: str = "",
    ) -> None:
        self._store_path = Path(store_path)
        self._navigator = navigator
        self._max_sections = max_sections
        self._reason = unavailable_reason
        self._cache_size = cache_size
        self._namespace = cache_namespace
        self.last_stats: NavigationStats | None = None

    @classmethod
    def unavailable(cls, reason: str) -> "PageIndexBackend":
        return cls("", None, unavailable_reason=reason)

    def prepare(self, project: str) -> Prepared | None:
        """Load the project's outline from the store (local, no model call).

        None when the project has no indexed documents; PageIndexUnavailable when
        the backend cannot work at all.
        """
        if self._navigator is None:
            raise PageIndexUnavailable(self._reason or "no navigation model configured")
        with PageIndexStore(self._store_path, create=False) as store:
            sections = store.sections(project)
            if not sections:
                return None
            fingerprint = store.fingerprint(project)
        outline = [OutlineEntry(s.doc_key, s.node_id, s.path, s.text[: SNIPPET_CHARS * 3]) for s in sections]
        estimate = getattr(self._navigator, "estimate_prompt_tokens", None)
        return Prepared(project, sections, outline, fingerprint, estimate(outline) if estimate else 0)

    def navigate(self, prepared: Prepared, query: str) -> list[StoredSection]:
        """Ask the navigator for sections; results are cached per (project, index version, query)."""
        stats = self.last_stats = NavigationStats(est_prompt_tokens=prepared.est_prompt_tokens)
        key = (
            str(self._store_path), prepared.project, prepared.fingerprint, self._namespace,
            self._max_sections, hashlib.sha256(re.sub(r"\s+", " ", query).strip().casefold().encode()).hexdigest(),
        )
        start = time.perf_counter()
        try:
            if self._cache_size and key in _CACHE:
                _CACHE.move_to_end(key)
                chosen = _CACHE[key]
                stats.cache_hit = True
            else:
                chosen = self._navigator.select(query, prepared.outline, self._max_sections)
                stats.prompt_chars = getattr(self._navigator, "last_prompt_chars", 0)
                stats.usage = getattr(self._navigator, "last_usage", None)
                if self._cache_size:
                    _CACHE[key] = chosen
                    while len(_CACHE) > self._cache_size:
                        _CACHE.popitem(last=False)
        except PageIndexUnavailable:
            stats.outcome = "error"
            raise
        finally:
            stats.elapsed_ms = (time.perf_counter() - start) * 1000
        by_key = {(s.doc_key, s.node_id): s for s in prepared.sections}
        return [s for pair in chosen if (s := by_key.get(pair)) is not None and s.project == prepared.project]

    def retrieve(self, project: str, query: str) -> list[StoredSection] | None:
        """prepare + navigate. None when the project has no documents."""
        prepared = self.prepare(project)
        return None if prepared is None else self.navigate(prepared, query)
