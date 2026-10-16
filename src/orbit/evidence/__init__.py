"""Storage-neutral evidence-linked project memory domain."""

from .model import (
    EvidenceRecord,
    EvidenceSource,
    EvidenceType,
    KnowledgeBundle,
    KnowledgeRecord,
    KnowledgeType,
    LifecycleStatus,
    ReferenceStatus,
    VerificationStatus,
)
from .service import EvidenceLinkedMemoryService

__all__ = [
    "EvidenceLinkedMemoryService",
    "EvidenceRecord",
    "EvidenceSource",
    "EvidenceType",
    "KnowledgeBundle",
    "KnowledgeRecord",
    "KnowledgeType",
    "LifecycleStatus",
    "ReferenceStatus",
    "VerificationStatus",
]
