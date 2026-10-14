"""Explicit, human-reviewed automatic knowledge capture prototype."""

from .model import (
    CandidateCategory,
    CandidateCertainty,
    CaptureEvent,
    CaptureInput,
    CaptureResult,
    CaptureSourceReference,
    CaptureSourceType,
    KnowledgeCandidate,
    ReviewStatus,
    SuppressedCapture,
)
from .service import (
    CaptureCandidateRepository,
    CaptureError,
    CaptureRepositoryError,
    CaptureValidationError,
    CandidateNotFound,
    InMemoryCaptureRepository,
    InvalidReviewTransition,
    KnowledgeCapturePipeline,
    SensitiveContentRejected,
    evidence_sources_for,
)

__all__ = [
    "CandidateCategory",
    "CandidateCertainty",
    "CaptureCandidateRepository",
    "CaptureError",
    "CaptureEvent",
    "CaptureInput",
    "CaptureRepositoryError",
    "CaptureResult",
    "CaptureSourceReference",
    "CaptureSourceType",
    "CaptureValidationError",
    "CandidateNotFound",
    "InMemoryCaptureRepository",
    "InvalidReviewTransition",
    "KnowledgeCandidate",
    "KnowledgeCapturePipeline",
    "ReviewStatus",
    "SensitiveContentRejected",
    "SuppressedCapture",
    "evidence_sources_for",
]
