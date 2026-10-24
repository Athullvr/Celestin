"""Internal typed result of reading project-scoped Capability 1 knowledge.

Outcome, coverage, record issues, and limitations are separate concepts:
``outcome`` says whether the read happened and was in scope; ``coverage`` says
only what the source claimed about completeness; ``record_issues`` describe
individual returned records. Nothing here enumerates storage or verifies that a
read was complete, and project IDs are never derived from paths or other keys.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

from orbit.evidence.model import KnowledgeBundle

REPORTED_COMPLETE_LIMITATION = (
    "Completeness was reported by the source and was not independently verified."
)


class KnowledgeReadOutcome(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SCOPE_MISMATCH = "scope_mismatch"


class KnowledgeCoverage(str, Enum):
    """What the source asserted. There is deliberately no ``verified`` member."""

    UNKNOWN = "unknown"
    PARTIAL = "partial"
    REPORTED_COMPLETE = "reported_complete"


class KnowledgeReadFailureKind(str, Enum):
    UNAVAILABLE = "unavailable"
    INVALID_RESPONSE = "invalid_response"
    OTHER = "other"


class KnowledgeRecordIssueKind(str, Enum):
    MISSING_EVIDENCE = "missing_evidence"
    MISSING_CAPTURE_PROVENANCE = "missing_capture_provenance"


@dataclass(frozen=True, slots=True)
class KnowledgeReadFailure:
    kind: KnowledgeReadFailureKind
    message: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, KnowledgeReadFailureKind):
            raise TypeError("kind must be a KnowledgeReadFailureKind")
        _require_text(self.message, "failure message")


@dataclass(frozen=True, slots=True)
class KnowledgeRecordIssue:
    """A gap observed on one returned record; the missing data is never fabricated."""

    knowledge_id: str
    kind: KnowledgeRecordIssueKind
    detail: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.knowledge_id, "knowledge_id")
        if not isinstance(self.kind, KnowledgeRecordIssueKind):
            raise TypeError("kind must be a KnowledgeRecordIssueKind")
        if self.detail is not None:
            _require_text(self.detail, "issue detail")


def _require_text(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ValueError(f"{name} must be a non-empty string")


def detect_record_issues(bundles: Sequence[KnowledgeBundle]) -> tuple[KnowledgeRecordIssue, ...]:
    """Report evidence/provenance gaps that are visible in the supplied bundles."""
    issues: list[KnowledgeRecordIssue] = []
    for bundle in bundles:
        if not isinstance(bundle, KnowledgeBundle):
            raise TypeError("records must be KnowledgeBundle values")
        knowledge_id = bundle.record.knowledge_id
        if not bundle.evidence:
            issues.append(KnowledgeRecordIssue(knowledge_id, KnowledgeRecordIssueKind.MISSING_EVIDENCE))
        if bundle.record.capture_provenance is None:
            issues.append(
                KnowledgeRecordIssue(knowledge_id, KnowledgeRecordIssueKind.MISSING_CAPTURE_PROVENANCE)
            )
    return tuple(issues)


@dataclass(frozen=True, slots=True)
class KnowledgeReadResult:
    project_id: str
    outcome: KnowledgeReadOutcome
    records: tuple[KnowledgeBundle, ...] = ()
    coverage: KnowledgeCoverage = KnowledgeCoverage.UNKNOWN
    failure: KnowledgeReadFailure | None = None
    record_issues: tuple[KnowledgeRecordIssue, ...] = ()
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.project_id, "project_id")
        if not isinstance(self.outcome, KnowledgeReadOutcome):
            raise TypeError("outcome must be a KnowledgeReadOutcome")
        if not isinstance(self.coverage, KnowledgeCoverage):
            raise TypeError("coverage must be a KnowledgeCoverage")
        records = tuple(self.records)
        issues = tuple(self.record_issues)
        limitations = tuple(self.limitations)
        for limitation in limitations:
            _require_text(limitation, "limitation")
        if self.failure is not None and not isinstance(self.failure, KnowledgeReadFailure):
            raise TypeError("failure must be a KnowledgeReadFailure")

        if self.outcome is KnowledgeReadOutcome.SUCCEEDED:
            if self.failure is not None:
                raise ValueError("a successful read must not carry failure details")
            self._validate_records(records, issues)
            if self.coverage is KnowledgeCoverage.REPORTED_COMPLETE and (
                REPORTED_COMPLETE_LIMITATION not in limitations
            ):
                limitations += (REPORTED_COMPLETE_LIMITATION,)
        else:
            if records or issues:
                raise ValueError("a failed or scope-mismatched read must not return records or issues")
            if self.coverage is not KnowledgeCoverage.UNKNOWN:
                raise ValueError("a failed or scope-mismatched read cannot claim coverage")
        object.__setattr__(self, "records", records)
        object.__setattr__(self, "record_issues", issues)
        object.__setattr__(self, "limitations", limitations)

    def _validate_records(
        self, records: tuple[KnowledgeBundle, ...], issues: tuple[KnowledgeRecordIssue, ...]
    ) -> None:
        ids: set[str] = set()
        for bundle in records:
            if not isinstance(bundle, KnowledgeBundle):
                raise TypeError("records must be KnowledgeBundle values")
            if bundle.record.project != self.project_id or any(
                item.project != self.project_id for item in bundle.evidence
            ):
                raise ValueError("a successful read must not contain records from another project")
            if bundle.record.knowledge_id in ids:
                raise ValueError("duplicate knowledge_id in returned records")
            ids.add(bundle.record.knowledge_id)
        for issue in issues:
            if not isinstance(issue, KnowledgeRecordIssue):
                raise TypeError("record_issues must be KnowledgeRecordIssue values")
            if issue.knowledge_id not in ids:
                raise ValueError("record issue refers to a record that was not returned")

    @classmethod
    def succeeded(
        cls,
        project_id: str,
        records: Sequence[KnowledgeBundle] = (),
        *,
        coverage: KnowledgeCoverage = KnowledgeCoverage.UNKNOWN,
        limitations: Sequence[str] = (),
    ) -> KnowledgeReadResult:
        """A read that completed; ``coverage`` stays unknown unless the source says otherwise."""
        records = tuple(records)
        return cls(
            project_id,
            KnowledgeReadOutcome.SUCCEEDED,
            records,
            coverage,
            record_issues=detect_record_issues(records),
            limitations=tuple(limitations),
        )

    @classmethod
    def failed(
        cls,
        project_id: str,
        failure: KnowledgeReadFailure | None = None,
        *,
        limitations: Sequence[str] = (),
    ) -> KnowledgeReadResult:
        return cls(project_id, KnowledgeReadOutcome.FAILED, failure=failure, limitations=tuple(limitations))

    @classmethod
    def scope_mismatch(
        cls,
        project_id: str,
        failure: KnowledgeReadFailure | None = None,
        *,
        limitations: Sequence[str] = (),
    ) -> KnowledgeReadResult:
        return cls(
            project_id, KnowledgeReadOutcome.SCOPE_MISMATCH, failure=failure, limitations=tuple(limitations)
        )

    @property
    def is_success(self) -> bool:
        return self.outcome is KnowledgeReadOutcome.SUCCEEDED

    @property
    def is_reported_complete(self) -> bool:
        """True only when the source claimed completeness; this is not verification."""
        return self.is_success and self.coverage is KnowledgeCoverage.REPORTED_COMPLETE
