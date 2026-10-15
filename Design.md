# Design Proposal: Two Retrieval Paths

Celestin remains the owner of persistence, access control, retrieval candidates, provenance, and context assembly. The current path stays intact. An opt-in System 1 path adds a local decision step over the same authorized candidates, allowing a controlled comparison without changing MCP contracts or the SQLite source of truth.

Start with Julia-1: its published 144.3M-parameter model has a CPU runtime and chooses among supplied options. That matches shortlist ranking and this host’s lack of an active GPU. Its reported benchmark results are not evidence of Celestin retrieval quality; evaluate locally. CLM is a future candidate because its public project explicitly targets ranking retrieval pools, but its reference setup uses Qwen3-8B with GPU-backed vLLM.

The model sees only the query and bounded candidate excerpts. Its result may reorder candidates, never override authorization, decision status, provenance, or byte limits. Failures preserve baseline order. Keep both paths independently selectable and report quality alongside latency and resource costs; do not switch defaults without held-out evidence and human review.
