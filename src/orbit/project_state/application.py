"""Local application boundary for trusted project-state reconstruction.

This module composes the configured local-project resolver with the existing
read-only reconstructor. ``ProjectKnowledgeReader`` is an internal port only;
the repository currently has no production local implementation of it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence

from orbit.evidence.model import KnowledgeBundle

from .knowledge_read import (
    KnowledgeCoverage,
    KnowledgeReadOutcome,
    KnowledgeReadResult,
    KnowledgeRecordIssue,
)
from .local_projects import LocalProjectBinding, LocalProjectResolver
from .model import ProjectStateSnapshot
from .reconstructor import ProjectStateReconstructor


class ProjectContextScopeMismatchError(RuntimeError):
    """A resolver returned a binding for a different requested project."""


class ProjectKnowledgeReader(Protocol):
    """Internal seam for a project-scoped Knowledge read.

    Implementations receive the trusted local binding and must use an
    explicitly configured, approved mapping to the Knowledge scope they read.
    ``KnowledgeReadResult.project_id`` remains that Knowledge scope ID; it is
    never assumed to equal ``LocalProjectBinding.project_id``. The project ID
    is a lookup key, not authorization. No production local reader currently
    implements this port.
    """

    def read(self, binding: LocalProjectBinding) -> KnowledgeReadResult: ...


@dataclass(frozen=True, slots=True)
class ProjectContextResult:
    """Reconstructed Git state and its independent Knowledge-read status.

    This intentionally does not contain Retrieval's ``ContextBundle``. The
    snapshot and typed read remain separate from ranked retrieval context.
    """

    project_id: str  # Local project ID resolved by LocalProjectResolver.
    repository_root: str
    pinned_revision: str
    reconstruction: ProjectStateSnapshot
    knowledge_read: KnowledgeReadResult | None
    knowledge_read_error: str | None
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.reconstruction.project_id != self.project_id:
            raise ValueError("reconstruction project does not match project context")
        if self.reconstruction.inspected_revision != self.pinned_revision:
            raise ValueError("pinned revision does not match reconstruction revision")
        object.__setattr__(self, "limitations", tuple(dict.fromkeys(self.limitations)))

    @property
    def knowledge_read_outcome(self) -> KnowledgeReadOutcome | None:
        return self.knowledge_read.outcome if self.knowledge_read is not None else None

    @property
    def knowledge_coverage(self) -> KnowledgeCoverage | None:
        return self.knowledge_read.coverage if self.knowledge_read is not None else None

    @property
    def record_issues(self) -> tuple[KnowledgeRecordIssue, ...]:
        return self.knowledge_read.record_issues if self.knowledge_read is not None else ()


class _KnowledgeReadSource:
    """Adapt an already performed typed read for the reconstructor's source port."""

    def __init__(self, binding: LocalProjectBinding, reader: ProjectKnowledgeReader | None) -> None:
        self._binding = binding
        self._reader = reader
        self.result: KnowledgeReadResult | None = None
        self.error: str | None = None

    def read(self) -> None:
        if self._reader is None:
            self.error = "No production local Knowledge reader is implemented or connected."
            return

        try:
            result = self._reader.read(self._binding)
        except Exception as exc:
            self.error = f"Knowledge reader raised {type(exc).__name__}; no records were used."
            return

        if not isinstance(result, KnowledgeReadResult):
            self.error = "Knowledge reader did not return a KnowledgeReadResult; no records were used."
            return

        self.result = result

    def list_records(self) -> Sequence[KnowledgeBundle]:
        if self.result is not None and self.result.outcome is KnowledgeReadOutcome.SUCCEEDED:
            return self.result.records
        return ()


class ProjectContextService:
    """Resolve an explicit local ID and reconstruct its pinned Git revision.

    A configured resolver is required. When no reader is supplied, the result
    reports that no typed Knowledge read was performed; there is no fallback
    enumeration or inference from retrieval records.
    """

    def __init__(
        self,
        resolver: LocalProjectResolver,
        *,
        knowledge_reader: ProjectKnowledgeReader | None = None,
    ) -> None:
        self._resolver = resolver
        self._knowledge_reader = knowledge_reader

    def reconstruct(self, project_id: str, revision: str = "HEAD") -> ProjectContextResult:
        """Reconstruct a configured project without reading or changing its worktree."""
        binding = self._resolver.resolve(project_id)
        if not isinstance(binding, LocalProjectBinding):
            raise TypeError("project resolver must return a LocalProjectBinding")
        if binding.project_id != project_id:
            raise ProjectContextScopeMismatchError(
                "resolved project ID does not match the requested project"
            )

        source = _KnowledgeReadSource(binding, self._knowledge_reader)
        source.read()
        knowledge_project_id = (
            source.result.project_id if source.result is not None else None
        )
        snapshot = ProjectStateReconstructor(
            binding.repository_root,
            binding.project_id,
            knowledge_source=source,
            knowledge_project_id=knowledge_project_id,
        ).reconstruct(revision)
        read_result = source.result
        limitations = list(snapshot.limitations)
        if source.error is not None:
            limitations.append(source.error)
        if read_result is not None:
            limitations.extend(read_result.limitations)
        if read_result is None or read_result.outcome is not KnowledgeReadOutcome.SUCCEEDED:
            limitations.append(
                "No Knowledge records from this read were used in reconstruction."
            )
        if read_result is None or read_result.coverage in {
            KnowledgeCoverage.UNKNOWN,
            KnowledgeCoverage.PARTIAL,
        }:
            limitations.append(
                "Missing Knowledge records do not establish deletion or nonexistence."
            )
        limitations.append(
            "Missing Knowledge records are not interpreted as deleted or resolved."
        )
        limitations.append(
            "The pinned Git revision and Knowledge read are independent snapshots."
        )

        return ProjectContextResult(
            project_id=binding.project_id,
            repository_root=str(binding.repository_root),
            pinned_revision=snapshot.inspected_revision,
            reconstruction=snapshot,
            knowledge_read=read_result,
            knowledge_read_error=source.error,
            limitations=tuple(dict.fromkeys(limitations)),
        )
