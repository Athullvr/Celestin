# App Flow Proposal: Retrieval Comparison

1. MCP client calls the existing retrieval tool with project, query, and budget.
2. Celestin authorizes the project before accessing records.
3. Baseline mode runs today’s retrieval and ranking unchanged.
4. System 1 mode runs the same project-scoped candidate search, then asks local Julia-1 to choose/rank a bounded candidate shortlist using the query and excerpts.
5. Celestin validates returned candidate IDs, retains source metadata, applies existing decision filters and context-budget assembly, and returns the unchanged response shape.
6. If inference fails or returns an invalid choice, Celestin keeps baseline order and records a safe diagnostic without logging content.
7. The evaluation harness runs both modes against identical frozen questions, corpus, and budgets; it reports evidence quality, recall, bytes, latency, and fallback count.

The model never queries SQLite, changes decisions, bypasses authorization, or writes answers. The baseline remains the default throughout evaluation.
