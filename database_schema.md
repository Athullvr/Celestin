# Proposed Database Schema Impact

There is no database change for this experiment. SQLite remains Celestin’s source of truth; existing message, decision, document-section, and vector records are reused. No hosted PostgreSQL schema is involved.

System 1 operates on ephemeral candidate records already produced by authorized retrieval. It receives candidate IDs, type, and bounded text excerpts; its response contains ordering/choice data only. The application maps choices back to existing records and retains their original source metadata. Unknown or duplicate IDs are rejected and cause baseline-order fallback.

Do not persist model scores, prompts, or inferred decisions in SQLite for the initial experiment. Existing project filters, approved/draft/deprecated decision handling, source-message constraints, archive behavior, and context budgets remain authoritative. Evaluation data and results stay in the existing `eval/` workflow, not production tables.
