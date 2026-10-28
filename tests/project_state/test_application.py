from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from orbit.evidence.model import KnowledgeBundle, KnowledgeRecord, KnowledgeType
from orbit.project_state import (
    LocalProjectBinding,
    LocalProjectResolver,
    ProjectContextScopeMismatchError,
    ProjectContextService,
)
from orbit.project_state.knowledge_read import (
    KnowledgeCoverage,
    KnowledgeReadFailure,
    KnowledgeReadFailureKind,
    KnowledgeReadOutcome,
    KnowledgeReadResult,
    KnowledgeRecordIssueKind,
)
from orbit.project_state.local_projects import InvalidProjectRootError, UnknownProjectError


NOW = "2026-10-28T12:00:00.000000Z"
KNOWLEDGE_PROJECT = "knowledge-project-42"


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.invalid",
        },
    )
    return result.stdout.strip()


def repository(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "repo-directory-is-not-the-project-id"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@example.invalid")
    (root / "README.md").write_text("# Project\n\n- [ ] inspect release state\n", encoding="utf-8")
    git(root, "add", "README.md")
    git(root, "commit", "-q", "-m", "initial")
    return root, git(root, "rev-parse", "HEAD")


def bundle(project: str = "alpha", knowledge_id: str = "k1") -> KnowledgeBundle:
    record = KnowledgeRecord(
        knowledge_id=knowledge_id,
        project=project,
        knowledge_type=KnowledgeType.DECISION,
        claim="Use the selected project configuration.",
        created_at=NOW,
        updated_at=NOW,
    )
    return KnowledgeBundle(record=record, evidence=())


class Reader:
    def __init__(self, result=None, *, error: Exception | None = None):
        self.result = result
        self.error = error
        self.bindings: list[LocalProjectBinding] = []

    def read(self, binding: LocalProjectBinding) -> KnowledgeReadResult:
        self.bindings.append(binding)
        if self.error is not None:
            raise self.error
        return self.result


def make_service(root: Path, reader=None) -> ProjectContextService:
    return ProjectContextService(LocalProjectResolver({"alpha": root}), knowledge_reader=reader)


def test_explicit_project_id_resolves_configured_root_not_directory_name(tmp_path):
    root, _ = repository(tmp_path)
    reader = Reader(KnowledgeReadResult.succeeded(KNOWLEDGE_PROJECT))
    result = make_service(root, reader).reconstruct("alpha")

    assert result.project_id == "alpha"
    assert result.repository_root == str(root.resolve())
    assert len(reader.bindings) == 1
    assert reader.bindings[0].project_id == "alpha"
    assert reader.bindings[0].repository_root == root.resolve()


def test_unknown_project_fails_before_reader_is_called(tmp_path):
    root, _ = repository(tmp_path)
    reader = Reader(KnowledgeReadResult.succeeded(KNOWLEDGE_PROJECT))

    with pytest.raises(UnknownProjectError):
        make_service(root, reader).reconstruct("repo-directory-is-not-the-project-id")

    assert reader.bindings == []


def test_invalid_project_root_fails_closed(tmp_path):
    file_root = tmp_path / "not-a-repository"
    file_root.write_text("not a repo", encoding="utf-8")
    service = ProjectContextService(LocalProjectResolver({"alpha": file_root}))

    with pytest.raises(InvalidProjectRootError):
        service.reconstruct("alpha")


def test_resolver_binding_must_match_explicit_project_id(tmp_path):
    root, _ = repository(tmp_path)

    class WrongBindingResolver:
        def resolve(self, project_id: str) -> LocalProjectBinding:
            assert project_id == "alpha"
            return LocalProjectBinding("other", root)

    with pytest.raises(ProjectContextScopeMismatchError):
        ProjectContextService(WrongBindingResolver()).reconstruct("alpha")  # type: ignore[arg-type]


def test_empty_success_is_distinct_from_unavailable_reader(tmp_path):
    root, _ = repository(tmp_path)
    empty = make_service(root, Reader(KnowledgeReadResult.succeeded(KNOWLEDGE_PROJECT))).reconstruct("alpha")
    unavailable = make_service(root).reconstruct("alpha")

    assert empty.knowledge_read_outcome is KnowledgeReadOutcome.SUCCEEDED
    assert empty.knowledge_coverage is KnowledgeCoverage.UNKNOWN
    assert empty.knowledge_read.records == ()
    assert unavailable.knowledge_read is None
    assert unavailable.knowledge_read_outcome is None
    assert unavailable.knowledge_coverage is None
    assert unavailable.knowledge_read_error is not None
    assert any("production local Knowledge reader" in item for item in unavailable.limitations)


def test_failed_read_is_not_used_as_an_empty_success(tmp_path):
    root, _ = repository(tmp_path)
    failed = KnowledgeReadResult.failed(
        KNOWLEDGE_PROJECT,
        KnowledgeReadFailure(KnowledgeReadFailureKind.UNAVAILABLE, "source offline"),
    )

    result = make_service(root, Reader(failed)).reconstruct("alpha")

    assert result.knowledge_read_outcome is KnowledgeReadOutcome.FAILED
    assert result.knowledge_read.failure.message == "source offline"
    assert not result.reconstruction.decisions
    assert any("No Knowledge records" in item for item in result.limitations)


def test_partial_read_preserves_records_issues_and_non_deletion_limitations(tmp_path):
    root, _ = repository(tmp_path)
    partial = KnowledgeReadResult.succeeded(
        KNOWLEDGE_PROJECT,
        [bundle(KNOWLEDGE_PROJECT)],
        coverage=KnowledgeCoverage.PARTIAL,
        limitations=("One page could not be read.",),
    )

    result = make_service(root, Reader(partial)).reconstruct("alpha")

    assert result.knowledge_read_outcome is KnowledgeReadOutcome.SUCCEEDED
    assert result.knowledge_coverage is KnowledgeCoverage.PARTIAL
    assert len(result.reconstruction.decisions) == 1
    assert result.record_issues[0].knowledge_id == "k1"
    assert {issue.kind for issue in result.record_issues} == {
        KnowledgeRecordIssueKind.MISSING_EVIDENCE,
        KnowledgeRecordIssueKind.MISSING_CAPTURE_PROVENANCE,
    }
    assert "One page could not be read." in result.limitations
    assert any("do not establish deletion" in item for item in result.limitations)
    assert any("not interpreted as deleted or resolved" in item for item in result.limitations)
    assert any("independent snapshots" in item for item in result.limitations)


def test_reader_exception_is_not_reported_as_empty_success(tmp_path):
    root, _ = repository(tmp_path)
    result = make_service(root, Reader(error=OSError("offline"))).reconstruct("alpha")

    assert result.knowledge_read is None
    assert result.knowledge_read_outcome is None
    assert "OSError" in result.knowledge_read_error
    assert not result.reconstruction.decisions


def test_reported_complete_keeps_source_limitation(tmp_path):
    root, _ = repository(tmp_path)
    complete = KnowledgeReadResult.succeeded(
        KNOWLEDGE_PROJECT, coverage=KnowledgeCoverage.REPORTED_COMPLETE
    )

    result = make_service(root, Reader(complete)).reconstruct("alpha")

    assert result.knowledge_coverage is KnowledgeCoverage.REPORTED_COMPLETE
    assert any("not independently verified" in item for item in result.limitations)


def test_scope_mismatch_does_not_supply_records_to_reconstruction(tmp_path):
    root, _ = repository(tmp_path)
    mismatch = KnowledgeReadResult.scope_mismatch(KNOWLEDGE_PROJECT)

    result = make_service(root, Reader(mismatch)).reconstruct("alpha")

    assert result.knowledge_read_outcome is KnowledgeReadOutcome.SCOPE_MISMATCH
    assert result.knowledge_read.records == ()
    assert not result.reconstruction.decisions
    assert any("No Knowledge records" in item for item in result.limitations)


def test_knowledge_scope_id_is_not_assumed_to_equal_local_project_id(tmp_path):
    root, _ = repository(tmp_path)
    reader = Reader(
        KnowledgeReadResult.succeeded(KNOWLEDGE_PROJECT, [bundle(KNOWLEDGE_PROJECT)])
    )
    result = make_service(root, reader).reconstruct("alpha")

    assert result.project_id == "alpha"
    assert result.knowledge_read.project_id == KNOWLEDGE_PROJECT
    assert result.reconstruction.project_id == "alpha"
    assert result.knowledge_read_outcome is KnowledgeReadOutcome.SUCCEEDED
    assert len(result.reconstruction.decisions) == 1


def test_pins_revision_and_does_not_mutate_worktree_or_mix_retrieval_context(tmp_path):
    root, fixed_revision = repository(tmp_path)
    tracked = root / "README.md"
    tracked.write_text("# Dirty worktree\n\n- [ ] local-only marker\n", encoding="utf-8")
    untracked = root / "untracked.txt"
    untracked.write_text("untracked local data\n", encoding="utf-8")
    original_tracked = tracked.read_bytes()
    original_untracked = untracked.read_bytes()
    status_before = git(root, "status", "--porcelain")

    result = make_service(root, Reader(KnowledgeReadResult.succeeded(KNOWLEDGE_PROJECT))).reconstruct(
        "alpha", "HEAD"
    )

    assert result.pinned_revision == fixed_revision
    assert result.reconstruction.inspected_revision == fixed_revision
    assert not any("local-only marker" in finding.claim for finding in result.reconstruction.incomplete)
    assert tracked.read_bytes() == original_tracked
    assert untracked.read_bytes() == original_untracked
    assert git(root, "status", "--porcelain") == status_before
    assert not hasattr(result, "context_bundle")
