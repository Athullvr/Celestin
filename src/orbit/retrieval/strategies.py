"""Retrieval strategies behind one interface.

Each strategy takes a validated request and returns normalized ``Candidate`` records in best-first
order per retrieval method. Strategies only *find* records: eligibility policy (draft and deprecated
decisions, project mismatch), fusion, deduplication and the byte budget stay in the shared
ranking and context-building pipeline. Decision status always comes from SQLite.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from orbit.pageindex.backend import PageIndexBackend
from orbit.pageindex.errors import PageIndexUnavailable
from orbit.pageindex.routing import decide_route
from orbit.pageindex.sections import search_sections
from orbit.pageindex.store import PageIndexStore, StoredSection
from orbit.repositories.decisions import DecisionRepository
from orbit.retrieval.fts import FtsMessageSearch
from orbit.retrieval.relevance import excerpt_section
from orbit.semantic.search import SemanticSearch, SemanticUnavailable

logger = logging.getLogger(__name__)

MESSAGE = "chat_message"
DECISION = "canonical_decision"
SECTION = "document_section"


@dataclass(frozen=True, slots=True)
class Candidate:
    """A retrieved record, independent of the engine that found it."""

    record_id: str
    record_type: str
    project: str
    content: str
    timestamp: str | None
    source_id: str | None
    method: str  # fts | semantic | sections_fts | sections_semantic | pageindex
    rank: int  # 1-based position within (record_type, method)
    score: float | None  # engine-native score (BM25 or cosine); never compared across methods
    status: str | None = None
    source: dict[str, Any] = field(default_factory=dict)  # extra attribution (documents)
    tier: str | None = None  # FTS tier that produced a keyword hit (strict | no_stopwords | relaxed_or)


@dataclass(frozen=True)
class RetrievalRequest:
    project: str
    query: str
    limit: int
    token_budget: int
    relax: bool = True
    approved_strict_hit: bool = False


@dataclass
class StrategyResult:
    name: str
    candidates: list[Candidate] = field(default_factory=list)
    status: str = "ok"  # ok | skipped | unavailable
    detail: str | None = None  # reason for skipped/unavailable, or a note
    fts_tier: str | None = None
    decision_tier: str | None = None
    stale: int = 0
    navigation: dict | None = None
    elapsed_ms: float = 0.0

    @property
    def strong_hits(self) -> int:
        """Content hits that count as sufficient evidence for the selector.

        Semantic hits (already above the similarity cut-off) and PageIndex selections count; keyword
        hits count only when every term (or every non-stopword term) matched, not for the relaxed OR tier.
        """
        weak_fts = self.fts_tier == "relaxed_or"
        return sum(
            c.record_type != DECISION and not (weak_fts and c.method in ("fts", "sections_fts"))
            for c in self.candidates
        )

    @property
    def content_hits(self) -> int:
        """Messages and sections found (decisions are a policy pass, not primary evidence)."""
        return sum(c.record_type != DECISION for c in self.candidates)


class Strategy(Protocol):
    name: str

    def retrieve(self, request: RetrievalRequest) -> StrategyResult: ...


def section_candidate(section: StoredSection, method: str, rank: int, score: float | None = None,
                      *, query: str = "", excerpt_bytes: int | None = None, tier: str | None = None) -> Candidate:
    content, ranges = excerpt_section(section.text, section.line_num, query, excerpt_bytes)
    return Candidate(
        record_id=f"doc:{section.doc_key}#{section.node_id}",
        record_type=SECTION,
        project=section.project,
        content=content,
        timestamp=section.indexed_at,
        source_id=section.doc_key,
        method=method,
        rank=rank,
        score=score,
        tier=tier,
        source={
            "document": section.doc_key,
            "section": " > ".join(section.path),
            "node_id": section.node_id,
            "line": section.line_num,
            "source_path": section.source_path,
            "content_hash": section.content_hash,
            **({"excerpted": True, "line_ranges": [list(r) for r in ranges]} if ranges else {}),
        },
    )


class FtsStrategy:
    """FTS5 over chat messages and decisions (strict first, bounded relaxation)."""

    name = "fts"

    def __init__(self, message_search: FtsMessageSearch, decision_search: FtsMessageSearch,
                 decisions: DecisionRepository) -> None:
        self._messages = message_search
        self._decision_search = decision_search
        self._decisions = decisions

    def retrieve(self, request: RetrievalRequest, kinds: tuple[str, ...] = (MESSAGE, DECISION)) -> StrategyResult:
        result = StrategyResult(self.name)
        if MESSAGE in kinds:
            found = self._messages.search(
                request.query, project_id=request.project, limit=request.limit, relax=request.relax
            )
            result.fts_tier = self._messages.last_tier
            result.candidates += [
                Candidate(r.message_id, MESSAGE, r.project_id, r.content, r.timestamp, r.message_id,
                          "fts", rank, r.relevance_score)
                for rank, r in enumerate(found, start=1)
            ]
        if DECISION in kinds:
            found = self._decision_search.search(
                request.query, project_id=request.project, limit=request.limit, relax=request.relax
            )
            result.decision_tier = self._decision_search.last_tier
            rows = {int(r["id"]): r for r in self._decisions.list_for_project(request.project, include_deprecated=True)}
            rank = 0
            for r in found:
                row = rows.get(int(r.message_id))
                if row is None:  # index edited by hand: never emit without authoritative status
                    continue
                rank += 1
                result.candidates.append(decision_candidate(row, "fts", rank, r.relevance_score))
        return result


def decision_candidate(row, method: str, rank: int, score: float | None) -> Candidate:
    return Candidate(
        record_id=f"decision:{row['id']}", record_type=DECISION, project=row["project"],
        content=row["value"], timestamp=row["updated_at"],
        source_id=str(row["source_message_id"]) if row["source_message_id"] is not None else None,
        method=method, rank=rank, score=score, status=row["status"],
    )


class SemanticStrategy:
    """Vector search over chat messages and decisions; every hit is reloaded from SQLite."""

    name = "semantic"

    def __init__(self, semantic: SemanticSearch, connection: sqlite3.Connection,
                 decisions: DecisionRepository) -> None:
        self._semantic = semantic
        self._conn = connection
        self._decisions = decisions

    def retrieve(self, request: RetrievalRequest) -> StrategyResult:
        result = StrategyResult(self.name)
        if not request.query.strip():
            return result
        try:
            hits = self._semantic.search(
                request.project, request.query, kinds=(MESSAGE, DECISION), limit=request.limit
            )
        except SemanticUnavailable as exc:
            logger.warning("semantic search unavailable: %s", exc)
            return StrategyResult(self.name, status="unavailable", detail=str(exc))
        message_hits = hits[MESSAGE]
        marks = ",".join("?" * len(message_hits))
        rows = {
            int(r["id"]): r
            for r in (
                self._conn.execute(
                    f"SELECT * FROM chat_messages WHERE project = ? AND id IN ({marks})",
                    (request.project, *[h.record_id for h in message_hits]),
                ) if message_hits else []
            )
        }
        rank = 0
        for h in message_hits:
            row = rows.get(h.record_id)
            if row is None:
                result.stale += 1
                continue
            rank += 1
            result.candidates.append(Candidate(
                str(h.record_id), MESSAGE, row["project"], row["content"], row["created_at"],
                str(h.record_id), "semantic", rank, h.similarity))
        decisions = {int(r["id"]): r for r in self._decisions.list_for_project(request.project, include_deprecated=True)}
        rank = 0
        for h in hits[DECISION]:
            row = decisions.get(h.record_id)
            if row is None:
                result.stale += 1
                continue
            rank += 1
            result.candidates.append(decision_candidate(row, "semantic", rank, h.similarity))
        return result


class SectionStrategy:
    """Heading-section retrieval: FTS5 and (when embedded) semantic search over document sections."""

    name = "sections"

    def __init__(self, store_path: Path, semantic: SemanticSearch | None,
                 excerpt_bytes: int | None = None) -> None:
        self._store_path = Path(store_path)
        self._semantic = semantic
        self._excerpt_bytes = excerpt_bytes

    def has_documents(self, project: str) -> bool:
        try:
            with PageIndexStore(self._store_path, create=False) as store:
                return bool(store.documents(project))
        except PageIndexUnavailable:
            return False

    def retrieve(self, request: RetrievalRequest) -> StrategyResult:
        result = StrategyResult(self.name)
        try:
            with PageIndexStore(self._store_path, create=False) as store:
                if not store.documents(request.project):
                    return StrategyResult(self.name, status="skipped", detail="no documents indexed")
                found, tier = search_sections(
                    store, request.project, request.query, request.limit, relax=request.relax
                )
                result.fts_tier = tier
                result.candidates += [
                    section_candidate(s, "sections_fts", i, query=request.query,
                                      excerpt_bytes=self._excerpt_bytes, tier=tier)
                    for i, s in enumerate(found, start=1)
                ]
                if self._semantic is not None and request.query.strip():
                    try:
                        hits = self._semantic.search(
                            request.project, request.query, kinds=(SECTION,), limit=request.limit
                        )[SECTION]
                    except SemanticUnavailable as exc:
                        result.detail = f"section semantic search unavailable: {exc}"
                        hits = []
                    sections = store.by_row_ids(request.project, [h.record_id for h in hits])
                    rank = 0
                    for h in hits:
                        sec = sections.get(h.record_id)
                        if sec is None:
                            result.stale += 1
                            continue
                        rank += 1
                        result.candidates.append(section_candidate(
                            sec, "sections_semantic", rank, h.similarity, query=request.query,
                            excerpt_bytes=self._excerpt_bytes))
        except PageIndexUnavailable as exc:
            return StrategyResult(self.name, status="unavailable", detail=str(exc))
        return result


class PageIndexStrategy:
    """LLM navigation of the document outline (optional, costs a model call)."""

    name = "pageindex"

    def __init__(self, backend: PageIndexBackend) -> None:
        self._backend = backend

    def prepare_estimate(self, project: str):
        return self._backend.prepare(project)

    def retrieve(self, request: RetrievalRequest) -> StrategyResult:
        try:
            prepared = self._backend.prepare(request.project)
            if prepared is None:
                return StrategyResult(self.name, status="skipped", detail="no_documents")
            decision = decide_route(
                request.query, token_budget=request.token_budget,
                approved_strict_hit=request.approved_strict_hit, outline_tokens=prepared.est_prompt_tokens,
            )
            if not decision.use:
                return StrategyResult(self.name, status="skipped", detail=decision.reason)
            sections = self._backend.navigate(prepared, request.query)
        except PageIndexUnavailable as exc:
            logger.warning("PageIndex unavailable, continuing without it: %s", exc)
            stats = self._backend.last_stats
            return StrategyResult(self.name, status="unavailable", detail=str(exc),
                                  navigation=stats.as_dict() if stats else None)
        stats = self._backend.last_stats
        return StrategyResult(
            self.name, candidates=[section_candidate(s, "pageindex", i) for i, s in enumerate(sections, start=1)],
            navigation=stats.as_dict() if stats else None,
        )
