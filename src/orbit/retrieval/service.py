"""Production retrieval service combining SQLite FTS and canonical memory."""

from __future__ import annotations

import sqlite3

from orbit.repositories.decisions import DecisionRepository
from orbit.retrieval.context_builder import ContextBundle, build_context_bundle
from orbit.retrieval.fts import FtsMessageSearch, FtsSchema, SearchResult
from orbit.retrieval.ranking import RankingPolicy, RetrievalCandidate


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
        self._candidate_limit = candidate_limit

    def search_chat_history(
        self, project: str, query: str, limit: int
    ) -> list[SearchResult]:
        """Return project-scoped message search matches ordered by BM25.

        Each result includes the chat message ID, project, conversation ID as
        ``source_id``, content, timestamp, and relevance score.
        """
        return self._message_search.search(
            query, project_id=project, limit=limit
        )

    def retrieve_context(
        self, project: str, query: str, token_budget: int
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

        candidates: list[RetrievalCandidate] = [
            RetrievalCandidate.from_message_search_result(result)
            for result in message_results
        ]
        for result in decision_results:
            decision = decisions_by_id.get(int(result.message_id))
            if decision is None:
                # This should only occur if an index is manually modified;
                # don't emit a candidate without authoritative status data.
                continue
            candidates.append(
                RetrievalCandidate(
                    record_id=f"decision:{decision['id']}",
                    project_id=decision["project"],
                    source_id=result.source_id,
                    content=decision["value"],
                    timestamp=decision["updated_at"],
                    relevance_score=result.relevance_score,
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
