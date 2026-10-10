"""Synthetic retrieval fixtures; these are not production database records.

The field names below form a temporary fixture-only adapter schema. They are
deliberately isolated from production initialization and must be mapped to the
real Member 1 repository contract before integration.
"""

MESSAGES = [
    {
        "fixture_record_id": "message-alpha-1",
        "fixture_project_id": "project-alpha",
        "fixture_source_id": "source-session-1",
        "fixture_created_at": "2026-01-02T10:00:00Z",
        "fixture_text": "The alpha service uses a local cache.",
        "fixture_status": None,
    },
    {
        "fixture_record_id": "message-beta-1",
        "fixture_project_id": "project-beta",
        "fixture_source_id": "source-session-2",
        "fixture_created_at": "2026-01-03T10:00:00Z",
        "fixture_text": "The beta service uses a local cache.",
        "fixture_status": None,
    },
]

PROJECT_MEMORIES = [
    {
        "fixture_record_id": "memory-alpha-approved",
        "fixture_project_id": "project-alpha",
        "fixture_source_id": "source-session-3",
        "fixture_created_at": "2026-01-04T10:00:00Z",
        "fixture_text": "Approved decision: use SQLite as the source of truth.",
        "fixture_status": "approved",
    },
    {
        "fixture_record_id": "memory-alpha-draft",
        "fixture_project_id": "project-alpha",
        "fixture_source_id": "source-session-4",
        "fixture_created_at": "2026-01-05T10:00:00Z",
        "fixture_text": "Draft proposal: evaluate a different cache policy.",
        "fixture_status": "draft",
    },
    {
        "fixture_record_id": "memory-alpha-deprecated",
        "fixture_project_id": "project-alpha",
        "fixture_source_id": "source-session-5",
        "fixture_created_at": "2026-01-06T10:00:00Z",
        "fixture_text": "Deprecated decision: store canonical memory in files.",
        "fixture_status": "deprecated",
    },
]
