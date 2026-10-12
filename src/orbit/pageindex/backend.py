"""PageIndex retrieval backend: route, navigate, return traceable sections."""

from __future__ import annotations

import re
from pathlib import Path

from .errors import PageIndexUnavailable
from .navigator import OutlineEntry, SNIPPET_CHARS, TreeNavigator
from .store import PageIndexStore, StoredSection

_WORD = re.compile(r"\w+", re.UNICODE)
MIN_QUERY_WORDS = 3


def route(query: str) -> str | None:
    """Return a reason to skip PageIndex for this query, or None to use it.

    Short or identifier-like queries (error codes, names) are better served by
    FTS5 and cost no model call. PageIndex navigation is for natural-language questions.
    """
    if len(_WORD.findall(query)) < MIN_QUERY_WORDS:
        return f"query has fewer than {MIN_QUERY_WORDS} words"
    return None


class PageIndexBackend:
    def __init__(
        self,
        store_path: str | Path,
        navigator: TreeNavigator | None,
        *,
        max_sections: int = 5,
        unavailable_reason: str | None = None,
    ) -> None:
        self._store_path = Path(store_path)
        self._navigator = navigator
        self._max_sections = max_sections
        self._reason = unavailable_reason

    @classmethod
    def unavailable(cls, reason: str) -> "PageIndexBackend":
        return cls("", None, unavailable_reason=reason)

    def retrieve(self, project: str, query: str) -> list[StoredSection] | None:
        """Sections for ``query`` (best first), or None when there are no documents for the project.

        Raises PageIndexUnavailable for any failure; never returns invented sections.
        """
        if self._navigator is None:
            raise PageIndexUnavailable(self._reason or "no navigation model configured")
        with PageIndexStore(self._store_path, create=False) as store:
            sections = store.sections(project)
            if not sections:
                return None
            outline = [
                OutlineEntry(s.doc_key, s.node_id, s.path, s.text[:SNIPPET_CHARS * 3])
                for s in sections
            ]
            chosen = self._navigator.select(query, outline, self._max_sections)
            by_key = {(s.doc_key, s.node_id): s for s in sections}
            # Re-resolve through the store so project and ids are authoritative.
            return [s for pair in chosen if (s := by_key.get(pair)) is not None and s.project == project]
