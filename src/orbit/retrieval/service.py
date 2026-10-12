"""Production retrieval service combining SQLite FTS and canonical memory."""

from __future__ import annotations

import logging
import sqlite3
from contextlib import closing
from dataclasses import asdict, replace
from typing import Any

from orbit.database.engine import connect
from orbit.repositories.decisions import DecisionRepository
from orbit.retrieval.context_builder import ContextBundle, build_context_bundle
from orbit.retrieval.fts import FtsMessageSearch, FtsSchema, SearchResult
from orbit.retrieval.hybrid import RRF_K, RetrievalInfo, reciprocal_rank_fusion
from orbit.retrieval.ranking import RankingPolicy, RetrievalCandidate
from pathlib import Path

from orbit.pageindex.backend import PageIndexBackend
from orbit.pageindex.errors import PageIndexUnavailable
from orbit.retrieval.selector import SelectorContext, plan_query
from orbit.retrieval.strategies import (
    Candidate, FtsStrategy, PageIndexStrategy, RetrievalRequest, SectionStrategy, SemanticStrategy, StrategyResult,
)
from orbit.semantic.search import SemanticSearch, SemanticUnavailable

logger = logging.getLogger(__name__)
MESSAGE_KIND = "chat_message"
DECISION_KIND = "canonical_decision"
DOCUMENT_KIND = "document_section"


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
        documents: PageIndexBackend | None = None,
        rrf_k: int = RRF_K,
        fts_relax: bool = True,
        sections: str | Path | None = None,
        selector: str = "all",
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
        self._fts_relax = fts_relax
        self._documents = documents
        if selector not in {"all", "adaptive"}:
            raise ValueError("selector must be 'all' or 'adaptive'")
        self._selector = selector
        self._sections = SectionStrategy(Path(sections), semantic) if sections is not None else None
        self._strategies: dict = {
            "fts": FtsStrategy(self._message_search, self._decision_search, self._decisions),
        }
        if semantic is not None:
            self._strategies["semantic"] = SemanticStrategy(semantic, connection, self._decisions)
        if self._sections is not None:
            self._strategies["sections"] = self._sections
        if documents is not None:
            self._strategies["pageindex"] = PageIndexStrategy(documents)
        self._executed: dict[str, StrategyResult] = {}
        self.last_retrieval = RetrievalInfo()
        # record_id -> source reference for document_section items of the last retrieve_context.
        self.last_sources: dict[str, dict[str, Any]] = {}
        self._navigation: dict | None = None

    @property
    def semantic_enabled(self) -> bool:
        return self._semantic is not None

    @property
    def documents_enabled(self) -> bool:
        return self._documents is not None or self._sections is not None or self._selector == "adaptive"

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
            relax=self._fts_relax,
        )
        hits = self._semantic_hits(project, query, (MESSAGE_KIND,), self._candidate_limit)
        if hits is None:
            return fts[:limit]
        fused, stale = self._fuse_messages(project, fts, hits[MESSAGE_KIND])
        self._note_stale(stale)
        return fused[:limit]

    # ---- strategy-based context retrieval -------------------------------------------------

    def _available(self) -> frozenset[str]:
        names = {"fts"}
        if self._semantic is not None:
            names.add("semantic")
        if self._sections is not None:
            names.add("sections")
        if self._documents is not None:
            names.add("pageindex")
        return frozenset(names)

    def _run(self, name: str, request: RetrievalRequest, **kwargs) -> StrategyResult:
        strategy = self._strategies[name]
        result = strategy.retrieve(request, **kwargs)
        self._executed[name] = result
        return result

    def _execute(self, request: RetrievalRequest) -> dict | None:
        """Run the strategies for this request; returns selector info in adaptive mode."""
        self._executed = {}
        available = self._available()
        if self._selector != "adaptive":
            fts = self._run("fts", request)
            approved = self._approved_strict_hit(fts)
            request = replace(request, approved_strict_hit=approved)
            for name in ("semantic", "sections", "pageindex"):
                if name in available:
                    self._run(name, request)
            return None
        has_documents = "sections" in available and self._strategies["sections"].has_documents(request.project)
        nav_tokens = None
        if "pageindex" in available:
            try:
                prepared = self._documents.prepare(request.project)
                has_documents = has_documents or prepared is not None
                nav_tokens = prepared.est_prompt_tokens if prepared else None
            except PageIndexUnavailable:
                available = available - {"pageindex"}
        plan = plan_query(request.query, SelectorContext(available, has_documents, request.token_budget, nav_tokens))
        info = {"mode": "adaptive", **plan.as_dict(), "fallback_used": False}
        if plan.primary == "fts":
            first = self._run("fts", request)
        else:
            # Approved decisions must stay reachable whatever the primary strategy is: a cheap local FTS pass.
            decisions = self._run("fts", request, kinds=("canonical_decision",))
            request = replace(request, approved_strict_hit=self._approved_strict_hit(decisions))
            first = self._run(plan.primary, request)
        if plan.fallback and not (first.status == "ok" and first.content_hits > 0):
            info["fallback_used"] = True
            self._run(plan.fallback, request)
        info["executed"] = [n for n in self._executed if not (n == "fts" and plan.primary != "fts" and
                                                              n not in plan.strategies)]
        return info

    @staticmethod
    def _approved_strict_hit(fts: StrategyResult) -> bool:
        return fts.decision_tier == "strict" and any(
            c.record_type == "canonical_decision" and c.status == "approved" for c in fts.candidates
        )

    def retrieve_context(
        self, project: str, query: str, token_budget: int = 2_000
    ) -> ContextBundle:
        """Assemble ranked message/decision/section candidates into a bounded bundle.

        Strategies (FTS5, semantic, heading sections, PageIndex) find candidates. When more than
        one retrieval method contributed, scores are Reciprocal Rank Fusion values (-score, lower
        is better); with FTS5 alone the BM25 scores are kept. Eligibility policy, deduplication
        and the byte budget are applied by the shared ranking and context builder.
        """
        request = RetrievalRequest(project, query, self._candidate_limit, token_budget, self._fts_relax)
        selector_info = self._execute(request)
        results = self._executed

        candidates_by_type: dict[str, dict[str, Candidate]] = {}
        lists: dict[tuple[str, str], list[Candidate]] = {}
        for name in ("fts", "semantic", "sections", "pageindex"):
            for c in results[name].candidates if name in results else []:
                lists.setdefault((c.record_type, c.method), []).append(c)
                candidates_by_type.setdefault(c.record_type, {}).setdefault(c.record_id, c)
        semantic_ok = "semantic" in results and results["semantic"].status == "ok"
        fused = semantic_ok or any(method != "fts" for _, method in lists)

        self.last_sources = {}
        candidates: list[RetrievalCandidate] = []
        for record_type, by_id in candidates_by_type.items():
            if fused:
                rankings = [[c.record_id for c in sorted(group, key=lambda c: c.rank)]
                            for (rt, _), group in lists.items() if rt == record_type]
                scores = {rid: -score for rid, score in reciprocal_rank_fusion(rankings, self._rrf_k)}
            else:
                scores = {rid: c.score for rid, c in by_id.items()}
            for rid, c in by_id.items():
                candidates.append(RetrievalCandidate(
                    record_id=c.record_id, project_id=c.project, source_id=c.source_id, content=c.content,
                    timestamp=c.timestamp, relevance_score=scores[rid], record_kind=c.record_type, status=c.status,
                ))
                if c.source:
                    self.last_sources[c.record_id] = c.source
        self.last_retrieval = self._describe(results, selector_info)
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

    def _describe(self, results: dict[str, StrategyResult], selector_info: dict | None) -> RetrievalInfo:
        warnings: list[str] = []
        mode, pageindex, sections, navigation = "fts", None, None, None
        sem = results.get("semantic")
        if sem is not None:
            if sem.status == "ok":
                mode = "hybrid"
                if sem.stale:
                    warnings.append(f"ignored {sem.stale} vector hit(s) with no matching SQLite record; "
                                    "run: celestin-index sync")
            else:
                mode = "fts_fallback"
                warnings.append(f"semantic search unavailable: {sem.detail}")
        elif self._semantic is not None and self._selector != "adaptive":
            mode = "hybrid"
        sec = results.get("sections")
        if self._sections is not None:
            if sec is None:
                sections = "not_selected"
            elif sec.status == "ok":
                sections = "used"
                if sec.detail:
                    warnings.append(sec.detail)
                if sec.stale:
                    warnings.append(f"ignored {sec.stale} section vector hit(s) with no matching section; "
                                    "run: celestin-index sync")
            else:
                sections = f"{sec.status}: {sec.detail}"
        pi = results.get("pageindex")
        if self._documents is not None:
            if pi is None:
                pageindex = "not_selected"
            elif pi.status == "ok":
                pageindex = "used"
            elif pi.status == "skipped" and pi.detail == "no_documents":
                pageindex = "no_documents"
            else:
                pageindex = f"{pi.status}: {pi.detail}"
                if pi.status == "unavailable":
                    warnings.append(f"document retrieval unavailable: {pi.detail}")
            navigation = pi.navigation if pi is not None else None
        return RetrievalInfo(mode, tuple(warnings), pageindex, navigation, sections, selector_info)


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
