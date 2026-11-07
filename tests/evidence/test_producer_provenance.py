from __future__ import annotations

from orbit.evidence.model import (
    EvidenceSource,
    EvidenceType,
    ProducerConflictReference,
    ProducerDeliveryProvenance,
    ProducerOccurrenceProvenance,
)
from orbit.evidence.provenance_json import (
    producer_delivery_from_dict,
    producer_delivery_to_dict,
)


def test_producer_provenance_round_trip_preserves_order_duplicates_and_links():
    source = EvidenceSource(
        EvidenceType.REPOSITORY_FILE,
        "repo-7",
        "README.md:8",
        "a1b2c3",
        "sha256:" + "a" * 64,
    )
    conflict = ProducerConflictReference("producer-b", "candidate-9", 4)
    repeated_occurrences = tuple(
        ProducerOccurrenceProvenance(
            ordinal=index,
            category="decision",
            claim="Keep the queue bounded.",
            source_namespace="git",
            source_id="repo-7",
            source_revision="a1b2c3",
            occurred_at="2026-11-01T10:00:00Z",
            locator="README.md:8",
            evidence=(source,),
            candidate_id="capture-candidate-1",
            candidate_revision=2,
            conflicts=(conflict,) if index == 1 else (),
        )
        for index in range(2)
    )
    provenance = ProducerDeliveryProvenance(
        schema_version=1,
        producer_id="trusted-producer",
        source_namespace="git",
        delivery_id="delivery-1",
        payload_revision_id="payload-r2",
        payload_hash_version="celestin-producer-delivery-v1+jcs-rfc8785+sha256",
        payload_hash="b" * 64,
        occurrences=repeated_occurrences,
        conflicts=(conflict,),
    )

    encoded = producer_delivery_to_dict(provenance)
    decoded = producer_delivery_from_dict(encoded)

    assert decoded == provenance
    assert [item.ordinal for item in decoded.occurrences] == [0, 1]
    assert [item.evidence for item in decoded.occurrences] == [(source,), (source,)]
    assert decoded.occurrences[0].conflicts == ()
    assert decoded.occurrences[1].conflicts == (conflict,)
    assert decoded.conflicts == (ProducerConflictReference("producer-b", "candidate-9", 4),)


def test_legacy_provenance_without_producer_extension_stays_unresolved():
    assert producer_delivery_from_dict(None) is None
