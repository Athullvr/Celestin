# PRD: Local System 1 Retrieval Experiment

## Summary

Compare Celestin’s existing retrieval path with an optional local System 1 decision-model path, without replacing storage, MCP tools, authorization, or context assembly.

## User and outcome

An agent asks the existing retrieval tools for project memory. The experiment should place more answer-bearing, relevant evidence into the same context budget, with provenance intact.

## Product behavior

- Keep today’s path as the default and make the experimental path explicitly selectable.
- Run both paths over the same frozen questions and corpus; report quality, context size, latency, and local resource use.
- Start with Julia-1 locally. It chooses among supplied candidates; it does not write answers or discover records by itself.
- Fall back safely to existing ranking if local inference is unavailable.

## Out of scope

Hosted inference, database migration, MCP contract changes, model training, and changing the default path.

## Acceptance

Existing behavior remains usable. On held-out questions, compare answer-bearing evidence and recall at equal budgets; publish tradeoffs without claiming improvement unless measurements support it.
