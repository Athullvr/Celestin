"""Stable JSON projection for versioned producer provenance."""

from __future__ import annotations

from typing import Any

from .model import (
    EvidenceSource,
    EvidenceType,
    ProducerConflictReference,
    ProducerDeliveryProvenance,
    ProducerOccurrenceProvenance,
)


def producer_delivery_to_dict(value: ProducerDeliveryProvenance) -> dict[str, Any]:
    """Serialize producer provenance without dropping ordered duplicates."""
    return {
        "schema_version": value.schema_version,
        "producer_id": value.producer_id,
        "source_namespace": value.source_namespace,
        "delivery_id": value.delivery_id,
        "payload_revision_id": value.payload_revision_id,
        "payload_hash_version": value.payload_hash_version,
        "payload_hash": value.payload_hash,
        "occurrences": [
            {
                "ordinal": item.ordinal,
                "category": item.category,
                "claim": item.claim,
                "source_namespace": item.source_namespace,
                "source_id": item.source_id,
                "source_revision": item.source_revision,
                "occurred_at": item.occurred_at,
                "locator": item.locator,
                "candidate_id": item.candidate_id,
                "candidate_revision": item.candidate_revision,
                "evidence": [
                    {
                        "evidence_type": evidence.evidence_type.value,
                        "source_id": evidence.source_id,
                        "locator": evidence.locator,
                        "revision": evidence.revision,
                        "content_hash": evidence.content_hash,
                    }
                    for evidence in item.evidence
                ],
            }
            for item in value.occurrences
        ],
        "conflicts": [
            {
                "producer_id": item.producer_id,
                "candidate_id": item.candidate_id,
                "candidate_revision": item.candidate_revision,
            }
            for item in value.conflicts
        ],
    }


def producer_delivery_from_dict(value: Any) -> ProducerDeliveryProvenance | None:
    """Parse stored producer provenance; malformed stored data fails closed."""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("producer_delivery must be an object")
    try:
        occurrences = tuple(
            ProducerOccurrenceProvenance(
                ordinal=item["ordinal"],
                category=item["category"],
                claim=item["claim"],
                source_namespace=item["source_namespace"],
                source_id=item["source_id"],
                source_revision=item.get("source_revision"),
                occurred_at=item.get("occurred_at"),
                locator=item.get("locator"),
                candidate_id=item["candidate_id"],
                candidate_revision=item["candidate_revision"],
                evidence=tuple(
                    EvidenceSource(
                        EvidenceType(evidence["evidence_type"]),
                        evidence["source_id"],
                        evidence.get("locator"),
                        evidence.get("revision"),
                        evidence.get("content_hash"),
                    )
                    for evidence in item["evidence"]
                ),
            )
            for item in value["occurrences"]
        )
        conflicts = tuple(
            ProducerConflictReference(**item) for item in value.get("conflicts", ())
        )
        return ProducerDeliveryProvenance(
            schema_version=value["schema_version"],
            producer_id=value["producer_id"],
            source_namespace=value["source_namespace"],
            delivery_id=value["delivery_id"],
            payload_revision_id=value["payload_revision_id"],
            payload_hash_version=value["payload_hash_version"],
            payload_hash=value["payload_hash"],
            occurrences=occurrences,
            conflicts=conflicts,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("producer_delivery provenance is invalid") from exc
