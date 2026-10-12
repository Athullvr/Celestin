"""Reproducible evaluation set: Celestin's own long documents plus a few chat memories.

Gold labels are content-based: a section is relevant when it lives in one of the
listed documents and its text contains the ``evidence`` string (case-insensitive).
"""

DOCS = [
    "README.md",
    "docs/interfaces.md",
    "docs/authorization-design.md",
    "docs/phase-8-investigation.md",
    "docs/retrieval.md",
    "docs/retrieval_integration.md",
    "docs/semantic-search.md",
]

# (query, evidence substring, documents that hold the answer)
DOC_QUERIES = [
    ("how big is the default embedding model download", "130 MB", ["README.md", "docs/semantic-search.md"]),
    ("why was sqlite-vec chosen over the alternatives", "LanceDB", ["docs/semantic-search.md"]),
    ("what happens when the embedding model cannot be reached", "fts_fallback", ["README.md", "docs/semantic-search.md"]),
    ("how are keyword and vector result lists combined", "Reciprocal Rank", ["README.md", "docs/semantic-search.md"]),
    ("which command registers the server with the coding agent", "codex mcp add", ["README.md"]),
    ("what is the largest context budget a caller may request", "20,000", ["README.md", "docs/interfaces.md"]),
    ("which ChatGPT plans can use write capable connectors", "Business", ["docs/phase-8-investigation.md"]),
    ("what is the error for a source message from another project", "SOURCE_MESSAGE_NOT_FOUND", ["docs/interfaces.md", "docs/authorization-design.md"]),
    ("how long may a decision value be", "100,000", ["docs/interfaces.md"]),
    ("which remote option avoids an inbound public listener", "does not require an inbound public listener", ["docs/phase-8-investigation.md"]),
    ("what stays unchanged when semantic search is switched off", "Unset", ["README.md", "docs/semantic-search.md"]),
    ("how does the vector index recover after an interrupted run", "re-run it", ["docs/semantic-search.md"]),
]

# Chat memories and queries: regression check that document retrieval does not hurt chat recall.
CHAT_MESSAGES = [
    "Decision meeting: we will keep deployment simple and avoid a hosted database for the demo.",
    "The nightly job failed with error ERR_PAYMENT_4471 after the card gateway changed its schema.",
    "Standup note: Priya owns the onboarding checklist and Marco owns the release notes.",
    "Design thought: caching search results for sixty seconds would cut repeated load a lot.",
    "Reminder that the hackathon submission is due at ten in the morning on the eleventh.",
]
CHAT_QUERIES = [
    ("ERR_PAYMENT_4471", "ERR_PAYMENT_4471"),
    ("who owns the release notes", "Marco owns the release notes"),
    ("why avoid a hosted database", "avoid a hosted database"),
    ("when is the hackathon submission due", "submission is due"),
    ("caching search results idea", "caching search results"),
]
