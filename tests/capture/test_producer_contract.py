from __future__ import annotations

from dataclasses import replace

import pytest

from orbit.capture.model import CandidateCategory, CaptureSourceType
from orbit.capture.producer_contract import (
    PRODUCER_DELIVERY_HASH_VERSION,
    ProducerDelivery,
    ProducerDeliveryValidationError,
    ProducerEvidenceReference,
    ProducerOccurrence,
)
from orbit.evidence.model import EvidenceType, ProducerConflictReference


def evidence(source_id: str = "repo-7") -> ProducerEvidenceReference:
    return ProducerEvidenceReference(
        EvidenceType.REPOSITORY_FILE,
        source_id,
        "git",
        locator="README.md:8",
        revision="a1b2c3",
        content_hash="sha256:" + "a" * 64,
    )


def occurrence(
    ordinal: int,
    claim: str = "Keep the queue bounded.",
    *,
    conflicts: tuple[ProducerConflictReference, ...] = (),
) -> ProducerOccurrence:
    return ProducerOccurrence(
        ordinal,
        CandidateCategory.DECISION,
        claim,
        (evidence(),),
        source_id="repo-7",
        source_revision="a1b2c3",
        occurred_at=f"2026-11-0{ordinal + 1}T10:00:00Z",
        locator="README.md:8",
        conflicts=conflicts,
    )


def delivery(*occurrences: ProducerOccurrence, revision: str = "payload-r1") -> ProducerDelivery:
    return ProducerDelivery(
        project_id="workspace-project-key",
        producer_id="trusted-producer",
        source_namespace="git",
        delivery_id="delivery-1",
        payload_revision_id=revision,
        source_type=CaptureSourceType.EXECUTION_REPORT,
        source_id="run-9",
        occurred_at="2026-11-01T10:00:00+00:00",
        occurrences=tuple(occurrences),
    )


def test_delivery_hash_binds_delivery_revision_order_and_duplicate_occurrences():
    first = occurrence(0)
    repeated = occurrence(1)
    item = delivery(first, repeated)
    changed_revision = delivery(first, repeated, revision="payload-r2")
    changed_order = delivery(
        occurrence(0, "Run the checks before release."),
        occurrence(1, "Keep the queue bounded."),
    )

    assert len(item.payload_document()["occurrences"]) == 2
    encoded_occurrences = item.payload_document()["occurrences"]
    assert [value["ordinal"] for value in encoded_occurrences] == [0, 1]
    assert [value["claim"] for value in encoded_occurrences] == [
        "Keep the queue bounded.", "Keep the queue bounded."
    ]
    assert item.payload_hash() != changed_revision.payload_hash()
    assert item.payload_hash() != changed_order.payload_hash()
    assert PRODUCER_DELIVERY_HASH_VERSION == "celestin-producer-delivery-v1+jcs-rfc8785+sha256"


def test_delivery_carries_typed_conflicts_and_source_provenance():
    conflict = ProducerConflictReference("other-producer", "candidate-5", 3)
    item = delivery(occurrence(0, conflicts=(conflict,)))

    payload = item.payload_document()
    assert payload["producer_id"] == "trusted-producer"
    assert payload["source_namespace"] == "git"
    assert payload["delivery_id"] == "delivery-1"
    assert payload["payload_revision_id"] == "payload-r1"
    assert payload["occurrences"][0]["occurred_at"] == "2026-11-01T10:00:00Z"
    assert payload["occurrences"][0]["category"] == "decision"
    assert payload["occurrences"][0]["conflicts"] == [
        {"producer_id": "other-producer", "candidate_id": "candidate-5", "candidate_revision": 3}
    ]


def test_delivery_rejects_missing_evidence_malformed_time_and_noncontiguous_ordinals():
    with pytest.raises(ProducerDeliveryValidationError, match="no evidence"):
        ProducerOccurrence(0, CandidateCategory.DECISION, "Claim", ())

    with pytest.raises(ProducerDeliveryValidationError, match="timezone"):
        delivery(replace(occurrence(0), occurred_at="2026-11-01T10:00:00"))

    with pytest.raises(ProducerDeliveryValidationError, match="contiguous"):
        delivery(occurrence(1))


def test_delivery_rejects_wrong_evidence_namespace_and_unsupported_contract_version():
    wrong_namespace = ProducerEvidenceReference(EvidenceType.OTHER, "x", "other")
    with pytest.raises(ProducerDeliveryValidationError, match="namespace"):
        delivery(ProducerOccurrence(0, CandidateCategory.DECISION, "Claim", (wrong_namespace,)))

    with pytest.raises(ProducerDeliveryValidationError, match="schema_version"):
        replace(delivery(occurrence(0)), schema_version=2)
