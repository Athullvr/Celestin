from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from orbit.capture.application import ProducerKnowledgeApplication
from orbit.capture.model import CandidateCategory, CaptureSourceType
from orbit.capture.postgres import ProducerWorkflowError
from orbit.capture.producer_contract import (
    ProducerDelivery,
    ProducerEvidenceReference,
    ProducerOccurrence,
)
from orbit.evidence.model import EvidenceType
from orbit.mcp_server.hosted_identity import HostedRequestBoundary
from orbit.mcp_server.hosted_scope import VerifiedPrincipal
from orbit.project_state.knowledge_read import KnowledgeReadResult
from orbit.project_state.local_projects import LocalProjectBinding
from orbit.retrieval.knowledge import KnowledgeRetrievalResult


class Resolver:
    def resolve(self, project_id: str) -> LocalProjectBinding:
        return LocalProjectBinding(project_id, Path("/trusted/repository"))


class Authenticator:
    def authenticate(self, _context: object) -> VerifiedPrincipal:
        return VerifiedPrincipal("issuer", "subject", "human")


class WorkspaceBinding:
    def workspace_for(self, _principal, requested_workspace_id=None):
        return requested_workspace_id or UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")


class PrincipalStatus:
    def is_active(self, _principal) -> bool:
        return True


class Workflow:
    def __init__(self) -> None:
        self.deliveries = []
        self.read_result = KnowledgeReadResult.succeeded("hosted-project")

    def deliver(self, delivery: ProducerDelivery) -> str:
        self.deliveries.append(delivery)
        return "accepted"

    def read_knowledge(self) -> KnowledgeReadResult:
        return self.read_result

    def retrieve_knowledge(self, read_result, query, **_kwargs) -> KnowledgeRetrievalResult:
        return KnowledgeRetrievalResult(read_result, None, "succeeded")


class Executor:
    def __init__(self, workflow: Workflow) -> None:
        self.workflow = workflow
        self.calls: list[tuple[str, str, str]] = []

    def _execute_authorized_request(
        self, _resolver, _principal, project_key, action, operation, **_kwargs
    ):
        self.calls.append((project_key, action, "authorized"))
        return operation(SimpleNamespace(producer_knowledge=self.workflow))


def make_app() -> tuple[ProducerKnowledgeApplication, Workflow, Executor]:
    workflow = Workflow()
    executor = Executor(workflow)
    boundary = HostedRequestBoundary(
        authenticator=Authenticator(),
        workspace_binding=WorkspaceBinding(),
        principal_status=PrincipalStatus(),
        request_executor=executor,
    )
    app = ProducerKnowledgeApplication(
        Resolver(),
        boundary,
        {"alpha": "hosted-project"},
        {"alpha": "producer-bound-by-server"},
    )
    return app, workflow, executor


def delivery(*, project_id: str = "hosted-project", producer_id: str = "producer-bound-by-server"):
    evidence = ProducerEvidenceReference(EvidenceType.OTHER, "source-1", "local-source")
    return ProducerDelivery(
        project_id=project_id,
        producer_id=producer_id,
        source_namespace="local-source",
        delivery_id="delivery-1",
        payload_revision_id="revision-1",
        source_type=CaptureSourceType.EXECUTION_REPORT,
        source_id="run-1",
        occurrences=(ProducerOccurrence(
            0, CandidateCategory.DECISION, "Use the approved queue.", (evidence,)
        ),),
    )


def test_application_resolves_local_project_and_uses_configured_hosted_and_producer_ids():
    app, workflow, executor = make_app()

    result = app.deliver(
        "alpha",
        delivery(),
        transport_context=object(),
        workspace_selector="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    )

    assert result == "accepted"
    assert workflow.deliveries == [delivery()]
    assert executor.calls == [("hosted-project", "write", "authorized")]


@pytest.mark.parametrize(
    "item, error_code",
    [
        (delivery(project_id="attacker-project"), "project_scope_mismatch"),
        (delivery(producer_id="attacker-producer"), "producer_identity_mismatch"),
    ],
)
def test_application_rejects_caller_selected_project_or_producer_identity(item, error_code):
    app, workflow, executor = make_app()

    with pytest.raises(ProducerWorkflowError) as raised:
        app.deliver(
            "alpha",
            item,
            transport_context=object(),
            workspace_selector="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        )

    assert getattr(raised.value, "code", None) == error_code
    assert workflow.deliveries == []
    assert executor.calls == []


def test_application_returns_typed_knowledge_read_and_separate_retrieval_projection():
    app, workflow, executor = make_app()

    result = app.retrieve_knowledge(
        "alpha",
        "queue",
        transport_context=object(),
        workspace_selector="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    )

    assert result.local_project_id == "alpha"
    assert result.knowledge_project_id == "hosted-project"
    assert result.knowledge_read is workflow.read_result
    assert isinstance(result.knowledge_read, KnowledgeReadResult)
    assert isinstance(result.retrieval, KnowledgeRetrievalResult)
    assert result.retrieval.knowledge_read is workflow.read_result
    assert executor.calls == [("hosted-project", "memory:read", "authorized")]
