from __future__ import annotations

import os
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from orbit.evidence.model import (
    EvidenceRecord,
    EvidenceType,
    KnowledgeBundle,
    KnowledgeRecord,
    KnowledgeType,
    LifecycleStatus,
    ReferenceStatus,
    VerificationStatus,
)
from orbit.project_state import (
    EvidenceClass,
    FindingKind,
    ProjectStateReconstructor,
    RepositoryInspectionError,
)


NOW = "2026-10-14T12:30:00.000000Z"


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


def repository(tmp_path: Path, files: dict[str, str] | None = None) -> Path:
    root = tmp_path / "sample-project"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@example.invalid")
    for name, content in (files or {}).items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


def commit(root: Path, message: str = "fixture") -> str:
    git(root, "add", "--all")
    git(root, "commit", "--allow-empty", "-q", "-m", message)
    return git(root, "rev-parse", "HEAD")


def reconstructor(root: Path, knowledge_source=None) -> ProjectStateReconstructor:
    return ProjectStateReconstructor(root, "sample-project", knowledge_source=knowledge_source)


def knowledge(
    knowledge_id: str,
    claim: str,
    *,
    kind: KnowledgeType = KnowledgeType.DECISION,
    status: VerificationStatus = VerificationStatus.UNVERIFIED,
    lifecycle: LifecycleStatus = LifecycleStatus.CURRENT,
    evidence: tuple[EvidenceRecord, ...] = (),
) -> KnowledgeBundle:
    record = KnowledgeRecord(
        knowledge_id=knowledge_id,
        project="sample-project",
        knowledge_type=kind,
        claim=claim,
        created_at=NOW,
        updated_at=NOW,
        verification_status=status,
        lifecycle_status=lifecycle,
    )
    return KnowledgeBundle(record, evidence)


class KnowledgeSource:
    def __init__(self, records):
        self.records = records

    def list_records(self):
        return self.records


def test_inspects_a_fixed_revision_and_ignores_worktree_changes(tmp_path):
    root = repository(tmp_path, {"src/module.py": "VALUE = 'committed'\n"})
    fixed = commit(root)
    (root / "src/module.py").write_text("VALUE = 'uncommitted'\n", encoding="utf-8")

    snapshot = reconstructor(root).reconstruct(fixed)

    assert snapshot.inspected_revision == fixed
    assert snapshot.is_current_head
    assert len(snapshot.implemented) == 1
    assert snapshot.implemented[0].classification is EvidenceClass.VERIFIED
    assert snapshot.implemented[0].evidence[0].source_type == "git_blob"
    assert snapshot.implemented[0].evidence[0].revision == fixed
    assert (root / "src/module.py").read_text(encoding="utf-8") == "VALUE = 'uncommitted'\n"


def test_open_work_is_inferred_and_completed_checklist_is_unverified(tmp_path):
    root = repository(
        tmp_path,
        {
            "src/app.py": "# TODO: add validation\n",
            "README.md": "- [ ] finish migration\n- [x] create app skeleton\n",
        },
    )
    commit(root)

    snapshot = reconstructor(root).reconstruct()

    assert {f.kind for f in snapshot.incomplete} == {FindingKind.INCOMPLETE}
    assert all(f.classification is EvidenceClass.INFERRED for f in snapshot.incomplete)
    completed = [f for f in snapshot.implemented if f.claim.startswith("Checklist marks complete")]
    assert len(completed) == 1
    assert completed[0].classification is EvidenceClass.UNVERIFIED
    assert all(f.evidence[0].path and f.evidence[0].line_start for f in snapshot.incomplete + tuple(completed))


def test_unresolved_section_is_reported_with_a_line_reference(tmp_path):
    root = repository(tmp_path, {"docs/status.md": "## Open Questions\n- Which cache backend?\n"})
    commit(root)

    snapshot = reconstructor(root).reconstruct()

    item = next(f for f in snapshot.unresolved if f.claim.endswith("Which cache backend?"))
    assert item.classification is EvidenceClass.INFERRED
    assert item.evidence[0].path == "docs/status.md"
    assert item.evidence[0].line_start == 2


def test_old_commit_is_historical_and_current_head_is_verified(tmp_path):
    root = repository(tmp_path, {"src/module.py": "VALUE = 1\n"})
    old = commit(root, "first")
    (root / "src/module.py").write_text("VALUE = 2\n", encoding="utf-8")
    commit(root, "second")

    old_snapshot = reconstructor(root).reconstruct(old)
    current_snapshot = reconstructor(root).reconstruct()

    assert old_snapshot.is_current_head is False
    assert old_snapshot.implemented[0].classification is EvidenceClass.HISTORICAL
    assert current_snapshot.is_current_head is True
    assert current_snapshot.implemented[0].classification is EvidenceClass.VERIFIED


def test_saved_decisions_keep_conflicts_and_missing_evidence_explicit(tmp_path):
    root = repository(tmp_path, {"src/db.py": "DATABASE = 'sqlite'\n"})
    head = commit(root)
    present = EvidenceRecord(
        "e-1", "sample-project", EvidenceType.REPOSITORY_FILE, "src/db.py", None,
        head, "not-checked-here", NOW, ReferenceStatus.AVAILABLE,
    )
    missing = EvidenceRecord(
        "e-2", "sample-project", EvidenceType.REPOSITORY_FILE, "src/missing.py", None,
        "old-revision", None, NOW, ReferenceStatus.MISSING,
    )
    source = KnowledgeSource(
        (
            knowledge("decision-a", "Use SQLite.", status=VerificationStatus.CONFLICTING, evidence=(present,)),
            knowledge("decision-b", "Use PostgreSQL.", status=VerificationStatus.CONFLICTING, evidence=(missing,)),
            knowledge("decision-c", "Unsupported claim."),
            knowledge(
                "decision-d",
                "Claim with missing source.",
                status=VerificationStatus.STALE,
                evidence=(missing,),
            ),
        )
    )

    decisions = reconstructor(root, source).reconstruct().decisions

    assert {item.claim for item in decisions} == {
        "Use PostgreSQL.", "Use SQLite.", "Unsupported claim.", "Claim with missing source."
    }
    conflicting = [item for item in decisions if item.claim in {"Use PostgreSQL.", "Use SQLite."}]
    assert all(item.classification is EvidenceClass.CONFLICTING for item in conflicting)
    assert all(item.applicability is EvidenceClass.UNKNOWN for item in decisions)
    missing_item = next(item for item in decisions if item.claim == "Use PostgreSQL.")
    assert "absent at inspected revision" in missing_item.evidence[0].detail
    assert missing_item.evidence[0].classification is EvidenceClass.STALE
    unsupported = next(item for item in decisions if item.claim == "Unsupported claim.")
    assert unsupported.classification is EvidenceClass.UNKNOWN
    assert unsupported.evidence[0].source_type == "knowledge_record"
    missing_claim = next(item for item in decisions if item.claim == "Claim with missing source.")
    assert missing_claim.classification is EvidenceClass.UNKNOWN
    assert missing_claim.recorded_verification == VerificationStatus.STALE.value
    current_item = next(item for item in decisions if item.claim == "Use SQLite.")
    assert "content hash was not verified" in current_item.evidence[0].detail


def test_superseded_memory_is_historical_not_current(tmp_path):
    root = repository(tmp_path, {"src/app.py": "READY = True\n"})
    commit(root)
    source = KnowledgeSource(
        (knowledge("old", "Use old interface.", lifecycle=LifecycleStatus.SUPERSEDED),)
    )

    decision = reconstructor(root, source).reconstruct().decisions[0]

    assert decision.classification is EvidenceClass.HISTORICAL
    assert decision.applicability is EvidenceClass.UNKNOWN


def test_readonly_knowledge_interface_with_no_records_reports_absence(tmp_path):
    root = repository(tmp_path, {"src/app.py": "READY = True\n"})
    commit(root)

    snapshot = reconstructor(root, KnowledgeSource(())).reconstruct()
    disconnected = reconstructor(root).reconstruct()

    assert snapshot.decisions == ()
    assert snapshot.recorded_knowledge == ()
    assert snapshot.unresolved == ()
    assert disconnected.decisions == ()
    assert disconnected.recorded_knowledge == ()
    assert any("no saved knowledge records were loaded" in item for item in disconnected.limitations)


def test_supplied_bundle_keeps_unverified_claim_separate_from_verified_reference(tmp_path):
    root = repository(tmp_path, {"src/db.py": "DATABASE = 'sqlite'\n"})
    head = commit(root)
    reference = EvidenceRecord(
        "e-db", "sample-project", EvidenceType.REPOSITORY_FILE, "src/db.py", "L1",
        head, "hash-not-checked", NOW, ReferenceStatus.AVAILABLE,
        VerificationStatus.VERIFIED, NOW, "reviewer",
    )
    claim = knowledge(
        "db-choice", "Use SQLite for local persistence.",
        status=VerificationStatus.VERIFIED,
        evidence=(reference,),
    )
    claim = KnowledgeBundle(
        replace(
            claim.record,
            checked_at=NOW,
            checked_by="caller-supplied-checker-label",
            check_note="checked against supplied evidence",
        ),
        claim.evidence,
    )

    decision = reconstructor(root, KnowledgeSource((claim,))).reconstruct().decisions[0]

    assert decision.classification is EvidenceClass.UNVERIFIED
    assert decision.recorded_verification == VerificationStatus.VERIFIED.value
    assert decision.verification_checked_at == NOW
    assert decision.verification_checked_by == "caller-supplied-checker-label"
    assert decision.verification_check_note == "checked against supplied evidence"
    assert decision.lifecycle_status == LifecycleStatus.CURRENT.value
    assert decision.applicability is EvidenceClass.UNKNOWN
    assert decision.evidence[0].classification is EvidenceClass.VERIFIED
    assert decision.evidence[0].path == "src/db.py"
    assert decision.evidence[0].evidence_record_id == "e-db"
    assert decision.evidence[0].locator == "L1"
    assert decision.evidence[0].content_hash == "hash-not-checked"
    assert decision.evidence[0].recorded_reference_status == ReferenceStatus.AVAILABLE.value
    assert decision.evidence[0].recorded_verification_status == VerificationStatus.VERIFIED.value
    assert decision.evidence[0].checked_by == "reviewer"
    assert "L1" in decision.evidence[0].detail
    assert "content hash was not verified" in decision.evidence[0].detail


def test_foreign_project_evidence_is_omitted_and_reported(tmp_path):
    root = repository(tmp_path, {"src/app.py": "READY = True\n"})
    commit(root)
    foreign = EvidenceRecord(
        "foreign-evidence", "another-project", EvidenceType.MESSAGE,
        "private-conversation-9", None, None, None, NOW,
        ReferenceStatus.AVAILABLE,
    )
    source = KnowledgeSource((knowledge("scoped-record", "Use SQLite.", evidence=(foreign,)),))

    snapshot = reconstructor(root, source).reconstruct()

    decision = snapshot.decisions[0]
    assert decision.classification is EvidenceClass.UNKNOWN
    assert all(item.source_id != "private-conversation-9" for item in decision.evidence)
    assert decision.evidence[0].source_type == "knowledge_record"
    assert any("evidence outside the requested project" in item for item in snapshot.limitations)


def test_supplied_bundle_preserves_historical_and_unverified_source_state(tmp_path):
    root = repository(tmp_path, {"src/db.py": "DATABASE = 'sqlite'\n"})
    old = commit(root, "old evidence revision")
    (root / "src/db.py").write_text("DATABASE = 'postgresql'\n", encoding="utf-8")
    head = commit(root, "current implementation")
    reference = EvidenceRecord(
        "e-old", "sample-project", EvidenceType.REPOSITORY_FILE, "src/db.py", "L1",
        old, None, NOW, ReferenceStatus.AVAILABLE,
    )
    claim = knowledge(
        "db-choice", "Use SQLite for local persistence.",
        status=VerificationStatus.UNVERIFIED,
        evidence=(reference,),
    )

    decision = reconstructor(root, KnowledgeSource((claim,))).reconstruct(head).decisions[0]

    assert decision.classification is EvidenceClass.UNVERIFIED
    assert decision.recorded_verification == VerificationStatus.UNVERIFIED.value
    assert decision.applicability is EvidenceClass.UNKNOWN
    assert decision.evidence[0].classification is EvidenceClass.HISTORICAL
    assert "current applicability is unchecked" in decision.evidence[0].detail


def test_unresolvable_bundle_evidence_remains_unknown_and_does_not_verify_claim(tmp_path):
    root = repository(tmp_path, {"src/app.py": "READY = True\n"})
    commit(root)
    reference = EvidenceRecord(
        "e-message", "sample-project", EvidenceType.MESSAGE, "conversation-7/message-3",
        "message-3", None, None, NOW, ReferenceStatus.UNRESOLVED,
        VerificationStatus.UNVERIFIED,
    )
    claim = knowledge(
        "message-claim", "The API migration is complete.",
        kind=KnowledgeType.COMPLETED_WORK,
        status=VerificationStatus.VERIFIED,
        evidence=(reference,),
    )

    finding = reconstructor(root, KnowledgeSource((claim,))).reconstruct().recorded_knowledge[0]

    assert finding.classification is EvidenceClass.UNKNOWN
    assert finding.recorded_verification == VerificationStatus.VERIFIED.value
    assert finding.evidence[0].classification is EvidenceClass.UNKNOWN
    assert "source reference not checked" in finding.evidence[0].detail


def test_knowledge_consumption_does_not_mutate_repository_or_database_artifact(tmp_path):
    root = repository(tmp_path, {"src/app.py": "READY = True\n"})
    commit(root)
    database_artifact = root / "local-memory.sqlite"
    database_artifact.write_bytes(b"unchanged test sentinel")
    before_status = git(root, "status", "--porcelain=v1", "--untracked-files=all")
    before_bytes = database_artifact.read_bytes()
    claim = knowledge("record-1", "A recorded claim.")

    result = reconstructor(root, KnowledgeSource((claim,))).reconstruct()

    assert result.decisions[0].classification is EvidenceClass.UNKNOWN
    assert git(root, "status", "--porcelain=v1", "--untracked-files=all") == before_status
    assert database_artifact.read_bytes() == before_bytes


def test_completed_work_is_preserved_as_an_unverified_claim_and_open_question(tmp_path):
    root = repository(tmp_path, {"src/app.py": "READY = True\n"})
    commit(root)
    source = KnowledgeSource(
        (
            knowledge("done", "The API migration is complete.", kind=KnowledgeType.COMPLETED_WORK),
            knowledge("question", "Should we remove the compatibility alias?", kind=KnowledgeType.OPEN_QUESTION),
        )
    )

    snapshot = reconstructor(root, source).reconstruct()

    completed = snapshot.recorded_knowledge[0]
    assert completed.claim == "The API migration is complete."
    assert completed.classification is EvidenceClass.UNKNOWN
    assert completed.knowledge_type == KnowledgeType.COMPLETED_WORK.value
    question = snapshot.unresolved[0]
    assert question.claim == "Should we remove the compatibility alias?"
    assert question.knowledge_type == KnowledgeType.OPEN_QUESTION.value
    assert question.evidence[0].source_type == "knowledge_record"


def test_missing_revision_and_non_repository_are_reported(tmp_path):
    root = repository(tmp_path, {"README.md": "Sample\n"})
    commit(root)
    with pytest.raises(RepositoryInspectionError, match="Needed a single revision"):
        reconstructor(root).reconstruct("does-not-exist")
    with pytest.raises(RepositoryInspectionError, match="not a git repository"):
        reconstructor(tmp_path).reconstruct()


def test_repository_root_boundary_and_symlink_blob_are_safe(tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("TODO: secret outside repo\n", encoding="utf-8")
    root = repository(tmp_path)
    (root / "docs").mkdir()
    (root / "docs/external.md").symlink_to(outside)
    commit(root)

    with pytest.raises(RepositoryInspectionError, match="worktree root"):
        reconstructor(root / "docs").reconstruct()
    snapshot = reconstructor(root).reconstruct()
    assert not any("secret outside repo" in finding.claim for finding in snapshot.incomplete)


def test_git_environment_cannot_redirect_inspection_to_another_repository(tmp_path, monkeypatch):
    root = repository(tmp_path, {"src/authorized.py": "AUTHORIZED = True\n"})
    commit(root)
    other_parent = tmp_path / "other"
    other_parent.mkdir()
    other = repository(other_parent, {"src/foreign.py": "FOREIGN = True\n"})
    commit(other)
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))

    snapshot = reconstructor(root).reconstruct()

    paths = {item.evidence[0].path for item in snapshot.implemented}
    assert paths == {"src/authorized.py"}


def test_empty_repository_and_output_are_deterministic(tmp_path):
    root = repository(tmp_path)
    commit(root, "empty")
    inspector = reconstructor(root)

    first = inspector.reconstruct()
    second = inspector.reconstruct()

    assert first == second
    assert first.implemented == ()
    assert first.incomplete == ()
    assert first.unresolved == ()
    assert first.next_steps[0].evidence[0].source_type == "git_tree"


def test_knowledge_reader_failure_is_reported_without_fabricated_state(tmp_path):
    root = repository(tmp_path, {"src/app.py": "READY = True\n"})
    commit(root)

    class BrokenReader:
        def list_records(self):
            raise OSError("offline")

    snapshot = reconstructor(root, BrokenReader()).reconstruct()

    assert snapshot.decisions == ()
    assert any("could not be read: OSError" in text for text in snapshot.limitations)
