"""HELD-OUT evaluation set (v1), written before any context-optimization experiment was run.

Same frozen corpus as dataset.py, different questions. Tune on the dev set (dataset.py); report this
set once for the configurations chosen on dev. Do not tune on it. Gold labels are content-based.
"""

HELDOUT_VERSION = "1"

DOC_QUERIES = [
    ("does the context builder ever clip a record to fit the budget", "never clips", ["docs/retrieval.md"]),
    ("how are exact duplicate records treated in the bundle", "included once", ["docs/retrieval.md"]),
    ("what does the default budget estimator count", "Utf8ByteTokenEstimator", ["docs/retrieval.md"]),
    ("which table backs the message index in production", "chat_messages_fts", ["docs/retrieval_integration.md", "docs/retrieval.md"]),
    ("how many results does each keyword search return by default", "result set to 100", ["docs/retrieval_integration.md"]),
    ("which permission is required for the tunnel runtime key", "Tunnels Read + Use", ["docs/authorization-design.md"]),
    ("what happens when a project member asks for another project", "Generic access denial", ["docs/authorization-design.md"]),
    ("which sqlite feature has to be enabled for the service", "FTS5 must be enabled", ["docs/retrieval_integration.md"]),
    ("what python version does the project require", "Python 3.10 or newer", ["README.md"]),
    ("what provenance does a decision keep when it has no source message", "null source ID", ["docs/retrieval.md"]),
    ("why does an unknown project look the same as an empty one", "There is no project registry", ["docs/retrieval.md", "docs/retrieval_integration.md"]),
    ("what is each included record rendered as", "one compact JSON object per line", ["docs/retrieval.md"]),
]

CHAT_MESSAGES = [
    "Sprint planning: Dana will own the migration checklist and Luis will handle the beta feedback review.",
    "We chose weekly releases on Thursdays because Friday deploys caused weekend incidents.",
    "Bug note: the exporter crashes with OSError ENOSPC when the temp volume is full.",
    "Idea for later: add a dark theme toggle to the settings page.",
]
CHAT_QUERIES = [
    ("OSError ENOSPC", "OSError ENOSPC"),
    ("who is handling the beta feedback review", "beta feedback review"),
    ("why do we release on thursdays", "weekly releases on Thursdays"),
    ("dark theme idea", "dark theme toggle"),
]
