"""Read-only, evidence-backed project-state reconstruction."""

from .application import (
    ProjectContextResult,
    ProjectContextScopeMismatchError,
    ProjectContextService,
    ProjectKnowledgeReader,
)
from .knowledge_read import (
    KnowledgeCoverage,
    KnowledgeReadFailure,
    KnowledgeReadFailureKind,
    KnowledgeReadOutcome,
    KnowledgeReadResult,
    KnowledgeRecordIssue,
    KnowledgeRecordIssueKind,
)
from .local_projects import (
    InvalidProjectConfigurationError,
    InvalidProjectIdError,
    InvalidProjectRootError,
    LocalProjectBinding,
    LocalProjectResolver,
    ProjectResolutionError,
    UnknownProjectError,
)
from .model import EvidenceClass, EvidenceReference, FindingKind, ProjectStateSnapshot, StateFinding
from .reconstructor import ProjectStateReconstructor, ReadOnlyKnowledgeSource, RepositoryInspectionError

__all__ = [
    "EvidenceClass",
    "EvidenceReference",
    "FindingKind",
    "InvalidProjectConfigurationError",
    "InvalidProjectIdError",
    "InvalidProjectRootError",
    "KnowledgeCoverage",
    "KnowledgeReadFailure",
    "KnowledgeReadFailureKind",
    "KnowledgeReadOutcome",
    "KnowledgeReadResult",
    "KnowledgeRecordIssue",
    "KnowledgeRecordIssueKind",
    "LocalProjectBinding",
    "LocalProjectResolver",
    "ProjectResolutionError",
    "ProjectContextResult",
    "ProjectContextScopeMismatchError",
    "ProjectContextService",
    "ProjectKnowledgeReader",
    "ProjectStateReconstructor",
    "ProjectStateSnapshot",
    "UnknownProjectError",
    "ReadOnlyKnowledgeSource",
    "RepositoryInspectionError",
    "StateFinding",
]
