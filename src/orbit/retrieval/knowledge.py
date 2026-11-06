"""FTS retrieval over typed, project-scoped Knowledge reads.

The returned ContextBundle is a ranked retrieval projection. It is separate
from both the authoritative KnowledgeReadResult and reconstructed project
state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from orbit.project_state.knowledge_read import (
    KnowledgeReadOutcome,
    KnowledgeReadResult,
)

from .context_builder import ContextBundle, build_context_bundle
from .knowledge_state import KnowledgeStateEnvelope
from .ranking import RankingPolicy, RetrievalCandidate


class KnowledgeSearchMatchLike(Protocol):
    knowledge_id: str
    project: str
    claim: str
    updated_at: str | None
    score: float


class KnowledgeSearchPageLike(Protocol):
    matches: tuple[KnowledgeSearchMatchLike, ...]
    tier: str


class KnowledgeSearchData(Protocol):
    def search_knowledge(
        self, project: str, query: str, limit: int, *, relax: bool
    ) -> KnowledgeSearchPageLike: ...


@dataclass(frozen=True, slots=True)
class KnowledgeRetrievalExclusion:
    knowledge_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class KnowledgeRetrievalResult:
    """A retrieval projection plus the exact typed read from which it came."""

    knowledge_read: KnowledgeReadResult
    context_bundle: ContextBundle | None
    search_outcome: str
    search_tier: str | None = None
    exclusions: tuple[KnowledgeRetrievalExclusion, ...] = ()
    failure: str | None = None


class KnowledgeRetrievalService:
    """Search a scoped Knowledge index and bind hits to the typed read result."""

    def __init__(self, data: KnowledgeSearchData) -> None:
        if not callable(getattr(data, "search_knowledge", None)):
            raise TypeError("data must provide search_knowledge")
        self._data = data

    def retrieve(
        self,
        read_result: KnowledgeReadResult,
        query: str,
        *,
        limit: int = 20,
        token_budget: int = 2_000,
        relax: bool = True,
        ranking_policy: RankingPolicy = RankingPolicy(),
    ) -> KnowledgeRetrievalResult:
        if not isinstance(read_result, KnowledgeReadResult):
            raise TypeError("read_result must be a KnowledgeReadResult")
        if read_result.outcome is not KnowledgeReadOutcome.SUCCEEDED:
            return KnowledgeRetrievalResult(
                read_result, None, "not_run", failure="knowledge_read_not_succeeded"
            )
        try:
            page = self._data.search_knowledge(
                read_result.project_id, query, limit, relax=relax
            )
        except Exception as exc:
            return KnowledgeRetrievalResult(
                read_result,
                None,
                "failed",
                failure=f"knowledge_search_failed:{type(exc).__name__}",
            )

        records = {bundle.record.knowledge_id: bundle for bundle in read_result.records}
        candidates: list[RetrievalCandidate] = []
        exclusions: list[KnowledgeRetrievalExclusion] = []
        seen: set[str] = set()
        for match in page.matches:
            knowledge_id = match.knowledge_id
            if knowledge_id in seen:
                exclusions.append(KnowledgeRetrievalExclusion(knowledge_id, "duplicate_search_identity"))
                continue
            seen.add(knowledge_id)
            if match.project != read_result.project_id:
                exclusions.append(KnowledgeRetrievalExclusion(knowledge_id, "project_mismatch"))
                continue
            bundle = records.get(knowledge_id)
            if bundle is None:
                exclusions.append(KnowledgeRetrievalExclusion(knowledge_id, "not_in_knowledge_read"))
                continue
            if bundle.record.claim != match.claim:
                exclusions.append(KnowledgeRetrievalExclusion(knowledge_id, "search_record_mismatch"))
                continue
            try:
                state = KnowledgeStateEnvelope.from_bundle(bundle)
            except Exception as exc:
                exclusions.append(
                    KnowledgeRetrievalExclusion(
                        knowledge_id, f"invalid_knowledge_provenance:{type(exc).__name__}"
                    )
                )
                continue
            candidates.append(
                RetrievalCandidate(
                    record_id=f"knowledge:{knowledge_id}",
                    project_id=read_result.project_id,
                    source_id=None,
                    content=bundle.record.claim,
                    timestamp=match.updated_at,
                    relevance_score=match.score,
                    record_kind="knowledge_record",
                    knowledge_state=state,
                )
            )

        try:
            context = build_context_bundle(
                candidates,
                project_id=read_result.project_id,
                token_budget=token_budget,
                ranking_policy=ranking_policy,
            )
        except Exception as exc:
            return KnowledgeRetrievalResult(
                read_result,
                None,
                "failed",
                search_tier=page.tier,
                exclusions=tuple(exclusions),
                failure=f"context_build_failed:{type(exc).__name__}",
            )
        return KnowledgeRetrievalResult(
            read_result,
            context,
            "succeeded",
            search_tier=page.tier,
            exclusions=tuple(exclusions),
        )
