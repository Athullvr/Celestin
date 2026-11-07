"""Application boundary for the internal Producer → Knowledge workflow.

The local project resolver and hosted project binding are independent. This
service requires an explicit configured mapping and performs every operation
through the existing authenticated hosted request boundary. It is not exposed
through MCP tools or an external producer transport.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Mapping, TypeVar

from orbit.mcp_server.hosted_identity import HostedRequestBoundary
from orbit.mcp_server.hosted_scope import ProjectAction
from orbit.project_state.knowledge_read import KnowledgeReadResult
from orbit.project_state.local_projects import LocalProjectBinding, LocalProjectResolver
from orbit.retrieval.knowledge import KnowledgeRetrievalResult

from .model import ReviewStatus
from .postgres import (
    CandidateReviewResult,
    KnowledgeConversionResult,
    PostgresProducerKnowledgeWorkflow,
    ProducerDeliveryReceipt,
    ProducerWorkflowError,
)
from .producer_contract import ProducerDelivery


@dataclass(frozen=True, slots=True)
class ProjectKnowledgeSearch:
    local_project_id: str
    knowledge_project_id: str
    knowledge_read: KnowledgeReadResult
    retrieval: KnowledgeRetrievalResult


ResultT = TypeVar("ResultT")


class ProducerKnowledgeApplication:
    """Compose configured local project selection with authorized operations."""

    def __init__(
        self,
        resolver: LocalProjectResolver,
        hosted_boundary: HostedRequestBoundary,
        hosted_project_keys: Mapping[str, str],
        producer_ids_by_local_project: Mapping[str, str],
        source_namespaces_by_local_project: Mapping[str, Sequence[str]],
    ) -> None:
        if not callable(getattr(resolver, "resolve", None)):
            raise TypeError("resolver must provide resolve(project_id)")
        if not isinstance(hosted_boundary, HostedRequestBoundary):
            raise TypeError("hosted_boundary must be a HostedRequestBoundary")
        mapping = dict(hosted_project_keys)
        producer_bindings = dict(producer_ids_by_local_project)
        namespace_bindings = dict(source_namespaces_by_local_project)
        if not mapping:
            raise ValueError("hosted_project_keys must contain an explicit project mapping")
        for local_id, hosted_key in mapping.items():
            if not isinstance(local_id, str) or not local_id.strip() or "\x00" in local_id:
                raise ValueError("local project mapping keys must be non-empty text")
            if not isinstance(hosted_key, str) or not hosted_key.strip() or "\x00" in hosted_key:
                raise ValueError("hosted project mapping values must be non-empty text")
        if set(producer_bindings) != set(mapping):
            raise ValueError("every local project must have one trusted producer binding")
        if set(namespace_bindings) != set(mapping):
            raise ValueError("every local project must have trusted source namespaces")
        for local_id, producer_id in producer_bindings.items():
            if (
                not isinstance(local_id, str)
                or not local_id.strip()
                or "\x00" in local_id
                or not isinstance(producer_id, str)
                or not producer_id.strip()
                or "\x00" in producer_id
            ):
                raise ValueError("producer bindings must contain non-empty project and producer IDs")
        normalized_namespaces: dict[str, frozenset[str]] = {}
        for local_id, namespaces in namespace_bindings.items():
            if not isinstance(namespaces, Sequence) or isinstance(namespaces, (str, bytes)):
                raise ValueError("source namespace bindings must be sequences of names")
            values = tuple(namespaces)
            if not values or any(
                not isinstance(value, str) or not value.strip() or "\x00" in value
                for value in values
            ):
                raise ValueError("source namespaces must be non-empty text")
            if len(set(values)) != len(values):
                raise ValueError("source namespace bindings must not contain duplicates")
            normalized_namespaces[local_id] = frozenset(values)
        self._resolver = resolver
        self._hosted_boundary = hosted_boundary
        self._hosted_project_keys = mapping
        self._producer_ids_by_local_project = producer_bindings
        self._source_namespaces_by_local_project = normalized_namespaces

    def deliver(
        self,
        local_project_id: str,
        delivery: ProducerDelivery,
        *,
        transport_context: object,
        workspace_selector: object,
    ) -> ProducerDeliveryReceipt:
        binding, hosted_key = self._select(local_project_id)
        if not isinstance(delivery, ProducerDelivery):
            raise ProducerWorkflowError("invalid_delivery", "delivery must be a ProducerDelivery")
        if delivery.project_id != hosted_key:
            raise ProducerWorkflowError(
                "project_scope_mismatch", "delivery project does not match the configured project mapping"
            )
        if delivery.producer_id != self._producer_ids_by_local_project[binding.project_id]:
            raise ProducerWorkflowError(
                "producer_identity_mismatch",
                "delivery producer does not match the trusted project producer binding",
            )
        if delivery.source_namespace not in self._source_namespaces_by_local_project[binding.project_id]:
            raise ProducerWorkflowError(
                "source_namespace_mismatch",
                "delivery source namespace is not configured for this project",
            )

        producer_id = self._producer_ids_by_local_project[binding.project_id]
        source_namespace = delivery.source_namespace

        def operation(workflow: PostgresProducerKnowledgeWorkflow) -> ProducerDeliveryReceipt:
            workflow.ensure_registered_source(producer_id, source_namespace)
            return workflow.deliver(delivery)

        return self._execute(
            binding,
            hosted_key,
            "write",
            operation,
            transport_context=transport_context,
            workspace_selector=workspace_selector,
        )

    def review(
        self,
        local_project_id: str,
        producer_id: str,
        candidate_id: str,
        candidate_revision: int,
        decision: ReviewStatus,
        *,
        note: str | None = None,
        transport_context: object,
        workspace_selector: object,
    ) -> CandidateReviewResult:
        binding, hosted_key = self._select(local_project_id)
        if decision not in {ReviewStatus.APPROVED, ReviewStatus.REJECTED}:
            raise ValueError("decision must be APPROVED or REJECTED")

        def operation(workflow: PostgresProducerKnowledgeWorkflow) -> CandidateReviewResult:
            if decision is ReviewStatus.APPROVED:
                return workflow.approve(producer_id, candidate_id, candidate_revision, note=note)
            return workflow.reject(producer_id, candidate_id, candidate_revision, note=note)

        return self._execute(
            binding,
            hosted_key,
            "candidate:approve",
            operation,
            transport_context=transport_context,
            workspace_selector=workspace_selector,
        )

    def convert(
        self,
        local_project_id: str,
        producer_id: str,
        candidate_id: str,
        candidate_revision: int,
        *,
        transport_context: object,
        workspace_selector: object,
    ) -> KnowledgeConversionResult:
        binding, hosted_key = self._select(local_project_id)
        return self._execute(
            binding,
            hosted_key,
            "memory:convert",
            lambda workflow: workflow.convert(producer_id, candidate_id, candidate_revision),
            transport_context=transport_context,
            workspace_selector=workspace_selector,
        )

    def read_knowledge(
        self,
        local_project_id: str,
        *,
        transport_context: object,
        workspace_selector: object,
    ) -> KnowledgeReadResult:
        binding, hosted_key = self._select(local_project_id)
        return self._execute(
            binding,
            hosted_key,
            "memory:read",
            lambda workflow: workflow.read_knowledge(),
            transport_context=transport_context,
            workspace_selector=workspace_selector,
        )

    def retrieve_knowledge(
        self,
        local_project_id: str,
        query: str,
        *,
        limit: int = 20,
        token_budget: int = 2_000,
        relax: bool = True,
        transport_context: object,
        workspace_selector: object,
    ) -> ProjectKnowledgeSearch:
        binding, hosted_key = self._select(local_project_id)

        def operation(workflow: PostgresProducerKnowledgeWorkflow) -> ProjectKnowledgeSearch:
            read_result = workflow.read_knowledge()
            retrieval = workflow.retrieve_knowledge(
                read_result,
                query,
                limit=limit,
                token_budget=token_budget,
                relax=relax,
            )
            return ProjectKnowledgeSearch(
                local_project_id=binding.project_id,
                knowledge_project_id=hosted_key,
                knowledge_read=read_result,
                retrieval=retrieval,
            )

        return self._execute(
            binding,
            hosted_key,
            "memory:read",
            operation,
            transport_context=transport_context,
            workspace_selector=workspace_selector,
        )

    def _select(self, local_project_id: str) -> tuple[LocalProjectBinding, str]:
        binding = self._resolver.resolve(local_project_id)
        if not isinstance(binding, LocalProjectBinding) or binding.project_id != local_project_id:
            raise ValueError("trusted project resolver returned an invalid project binding")
        hosted_key = self._hosted_project_keys.get(binding.project_id)
        if hosted_key is None:
            raise ValueError("local project has no explicit Knowledge project mapping")
        return binding, hosted_key

    def _execute(
        self,
        binding: LocalProjectBinding,
        hosted_key: str,
        action: ProjectAction,
        operation: Callable[[PostgresProducerKnowledgeWorkflow], ResultT],
        *,
        transport_context: object,
        workspace_selector: object,
    ) -> ResultT:
        # binding establishes trusted local selection; hosted_key is a separate
        # explicit mapping and authentication/authorization remain server-owned.
        if binding.project_id not in self._hosted_project_keys:
            raise ValueError("local project has no explicit Knowledge project mapping")
        return self._hosted_boundary.execute_authorized_request(
            transport_context,
            hosted_key,
            action,
            lambda unit_of_work: operation(unit_of_work.producer_knowledge),
            workspace_selector=workspace_selector,
        )
