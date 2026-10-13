"""Additional questions curated after the original reranker sweep; do not tune on this set."""

VERSION = "1"

DOC_QUERIES = [
    ("which role values are valid for ingesting a chat message", "system", ["docs/interfaces.md"]),
    ("what timestamp format does the MCP boundary serialize", "RFC 3339 / ISO 8601", ["docs/interfaces.md"]),
    ("why is vector data stored in a separate file", "existing databases are untouched", ["docs/semantic-search.md"]),
    ("what stale vectors are removed when a decision loses approval", "decision no longer approved", ["docs/semantic-search.md"]),
    ("where does project authorization happen in a remote request", "after transport authentication", ["docs/authorization-design.md"]),
    ("does the project argument prove that a caller has access", "must never be treated as proof of authorization", ["docs/authorization-design.md"]),
]

CHAT_MESSAGES = [
    "Platform note: uploads stay in the EU Central region.",
    "Ops plan: the nightly index rebuild runs at 02:30 UTC.",
    "Release decision: owners will publish docs every second Tuesday.",
]

CHAT_QUERIES = [
    ("where are uploads stored", "EU Central"),
    ("when does the nightly index rebuild run", "02:30 UTC"),
    ("when are docs published", "second Tuesday"),
]
