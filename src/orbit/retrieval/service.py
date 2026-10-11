"""Production retrieval service combining SQLite FTS and canonical memory."""

from __future__ import annotations

import logging
import sqlite3
from contextlib import closing
from dataclasses import asdict
from typing import Any

from orbit.database.engine import connect
from orbit.repositories.decisions import DecisionRepository
from orbit.retrieval.context_builder import ContextBundle, build_context_bundle
from orbit.retrieval.fts import FtsMessageSearch, FtsSchema, SearchResult
from orbit.retrieval.hybrid import RRF_K, RetrievalInfo, reciprocal_rank_fusion
from orbit.retrieval.ranking import RankingPolicy, RetrievalCandidate
from orbit.semantic.search import SemanticSearch, SemanticUnavailable

logger = logging.getLogger(__name__)
MESSAGE_KIND = "chat_message"
DECISION_KIND = "canonical_decision"


MESSAGE_FTS_SCHEMA = FtsSchema(
    table="chat_messages_fts",
    message_id="message_id",
    project_id="project_id",
    source_id="source_id",
    created_at="created_at",
    content="content",
)

DECISION_FTS_SCHEMA = FtsSchema(
    table="project_memory_fts",
    message_id="decision_id",
    project_id="project_id",
    source_id="source_id",
    created_at="updated_at",
    content="value",
)


class RetrievalService:
    """Project-scoped search and context assembly over the production schema.

    Pass the connection returned by :func:`orbit.database.engine.connect`.
    Schema migration 2 creates and synchronizes the two FTS5 indexes used here.
    """

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        candidate_limit: int = 100,
        semantic: SemanticSearch | None = None,
        rrf_k: int = RRF_K,
    ) -> None:
        if not isinstance(connection, sqlite3.Connection):
            raise TypeError("connection must be a sqlite3.Connection")
        if isinstance(candidate_limit, bool) or not isinstance(candidate_limit, int):
            raise TypeError("candidate_limit must be an integer")
        if candidate_limit < 1:
            raise ValueError("candidate_limit must be at least 1")

        self._message_search = FtsMessageSearch(connection, MESSAGE_FTS_SCHEMA)
        self._decision_search = FtsMessageSearch(connection, DECISION_FTS_SCHEMA)
        self._decisions = DecisionRepository(connection)
        self._connection = connection
        self._candidate_limit = candidate_limit
        self._semantic = semantic
        self._rrf_k = rrf_k
        self.last_retrieval = RetrievalInfo()

    @property
    def semantic_enabled(self) -> bool:
        return self._semantic is not None

    def _semantic_hits(self, project: str, query: str, kinds: tuple[str, ...], limit: int):
        """Vector hits per kind, or None when degraded to FTS5 (reason recorded)."""
        if self._semantic is None:
            self.last_retrieval = RetrievalInfo("fts")
            return None
        if not query.strip():
            self.last_retrieval = RetrievalInfo("hybrid")
            return {kind: [] for kind in kinds}
        try:
            hits = self._semantic.search(project, query, kinds=kinds, limit=limit)
        except SemanticUnavailable as exc:
            logger.warning("semantic search unavailable, using FTS5 only: %s", exc)
            self.last_retrieval = RetrievalInfo(
                "fts_fallback", (f"semantic search unavailable: {exc}",)
            )
            return None
        self.last_retrieval = RetrievalInfo("hybrid")
        return hits

    def _note_stale(self, count: int) -> None:
        if count:
            self.last_retrieval = RetrievalInfo(
                "hybrid",
                (f"ignored {count} vector hit(s) with no matching SQLite record; "
                 "run: celestin-index sync",),
            )

    def _load_messages(self, project: str, ids: list[int]) -> dict[int, sqlite3.Row]:
        """Authoritative message rows, re-filtered by project."""
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        rows = self._connection.execute(
            f"SELECT * FROM chat_messages WHERE project = ? AND id IN ({marks})",
            (project, *ids),
        )
        return {int(row["id"]): row for row in rows}

    def _fuse_messages(
        self, project: str, fts: list[SearchResult], vector_hits
    ) -> tuple[list[SearchResult], int]:
        """Merge FTS5 and vector message hits with RRF into SearchResults.

        ``relevance_score`` of fused results is ``-rrf_score`` so that, like
        BM25, a lower value is better.
        """
        by_id = {int(r.message_id): r for r in fts}
        rows = self._load_messages(
            project, [h.record_id for h in vector_hits if h.record_id not in by_id]
        )
        semantic_ids = [h.record_id for h in vector_hits if h.record_id in by_id or h.record_id in rows]
        stale = len(vector_hits) - len(semantic_ids)
        fused = reciprocal_rank_fusion([list(by_id), semantic_ids], self._rrf_k)
        results = []
        for record_id, score in fused:
            if record_id in by_id:
                base = by_id[record_id]
                results.append(SearchResult(
                    base.message_id, base.project_id, base.source_id,
                    base.content, base.timestamp, -score,
                ))
            else:
                row = rows[record_id]
                results.append(SearchResult(
                    str(record_id), row["project"], row["conversation_id"],
                    row["content"], row["created_at"], -score,
                ))
        return results, stale

    def search_chat_history(
        self, project: str, query: str, limit: int = 10
    ) -> list[SearchResult]:
        """Return project-scoped message search matches ordered by BM25.

        Each result includes the chat message ID, project, conversation ID in
        ``source_id``, content, timestamp, and relevance score.
        """
        fts = self._message_search.search(
            query, project_id=project, limit=max(limit, self._candidate_limit)
            if self._semantic is not None else limit,
        )
        hits = self._semantic_hits(project, query, (MESSAGE_KIND,), self._candidate_limit)
        if hits is None:
            return fts[:limit]
        fused, stale = self._fuse_messages(project, fts, hits[MESSAGE_KIND])
        self._note_stale(stale)
        return fused[:limit]

    def retrieve_context(
        self, project: str, query: str, token_budget: int = 2_000
    ) -> ContextBundle:
        """Assemble ranked message/decision candidates into a bounded bundle.

        Message relevance is the message-index BM25 score. Decision relevance
        is the decision-index BM25 score for its stored ``value``. The score is
        kept separate from approved-decision priority in ``RankingPolicy``.
        """
        message_results = self._message_search.search(
            query,
            project_id=project,
            limit=self._candidate_limit,
        )
        hits = self._semantic_hits(
            project, query, (MESSAGE_KIND, DECISION_KIND), self._candidate_limit
        )
        stale = 0
        if hits is not None:
            message_results, stale = self._fuse_messages(
                project, message_results, hits[MESSAGE_KIND]
            )
        decision_results = self._decision_search.search(
            query,
            project_id=project,
            limit=self._candidate_limit,
        )
        decisions_by_id = {
            int(row["id"]): row
            for row in self._decisions.list_for_project(
                project, include_deprecated=True
            )
        }

        decision_scores = [
            (int(r.message_id), r.relevance_score) for r in decision_results
        ]
        if hits is not None:
            fts_ids = [i for i, _ in decision_scores]
            semantic_ids = [
                h.record_id for h in hits[DECISION_KIND] if h.record_id in decisions_by_id
            ]
            stale += len(hits[DECISION_KIND]) - len(semantic_ids)
            decision_scores = [
                (i, -score)
                for i, score in reciprocal_rank_fusion([fts_ids, semantic_ids], self._rrf_k)
            ]
            self._note_stale(stale)

        candidates: list[RetrievalCandidate] = [
            RetrievalCandidate(
                record_id=result.message_id,
                project_id=result.project_id,
                source_id=result.message_id,
                content=result.content,
                timestamp=result.timestamp,
                relevance_score=result.relevance_score,
                record_kind="chat_message",
            )
            for result in message_results
        ]
        for decision_id, decision_score in decision_scores:
            decision = decisions_by_id.get(decision_id)
            if decision is None:
                # This should only occur if an index is manually modified;
                # don't emit a candidate without authoritative status data.
                continue
            candidates.append(
                RetrievalCandidate(
                    record_id=f"decision:{decision['id']}",
                    project_id=decision["project"],
                    source_id=(
                        str(decision["source_message_id"])
                        if decision["source_message_id"] is not None
                        else None
                    ),
                    content=decision["value"],
                    timestamp=decision["updated_at"],
                    relevance_score=decision_score,
                    record_kind="canonical_decision",
                    status=decision["status"],
                )
            )

        return build_context_bundle(
            candidates,
            project_id=project,
            token_budget=token_budget,
            ranking_policy=RankingPolicy(
                approved_decisions_first=True,
                include_drafts=False,
                include_deprecated=False,
            ),
        )


def _search_result_dict(result: SearchResult) -> dict[str, Any]:
    return {
        "message_id": result.message_id,
        "project": result.project_id,
        "source_message_id": result.message_id,
        "conversation_id": result.source_id,
        "role": None,
        "content": result.content,
        "created_at": result.timestamp,
        "score": result.relevance_score,
    }


def _context_bundle_dict(bundle: ContextBundle, query: str) -> dict[str, Any]:
    return {
        "project": bundle.project_id,
        "query": query,
        "items": [
            {
                "record_id": item.record_id,
                "project_id": item.project_id,
                "source_message_id": item.source_id,
                "created_at": item.timestamp,
                "record_kind": item.record_kind,
                "status": item.status,
                "content": item.content,
                "relevance_score": item.relevance_score,
            }
            for item in bundle.items
        ],
        "excluded": [
            {
                "record_id": item.record_id,
                "project_id": item.project_id,
                "source_message_id": item.source_id,
                "created_at": item.timestamp,
                "record_kind": item.record_kind,
                "status": item.status,
                "reason": item.reason,
            }
            for item in bundle.excluded
        ],
        "excluded_counts": [asdict(item) for item in bundle.excluded_counts],
        "rendered_context": bundle.rendered_context,
        "token_count": bundle.token_count,
        "token_budget": bundle.token_budget,
        "token_count_is_estimate": bundle.token_count_is_estimate,
        "token_counter": bundle.token_counter,
    }


def search_chat_history(
    project: str,
    query: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Search messages using the configured production SQLite database."""
    with closing(connect()) as connection:
        results = RetrievalService(connection).search_chat_history(
            project, query, limit
        )
    return [_search_result_dict(result) for result in results]


def retrieve_context(
    project: str,
    query: str,
    token_budget: int = 2_000,
) -> dict[str, Any]:
    """Return a serializable, traceable context bundle for one project."""
    with closing(connect()) as connection:
        bundle = RetrievalService(connection).retrieve_context(
            project, query, token_budget
        )
    return _context_bundle_dict(bundle, query)
