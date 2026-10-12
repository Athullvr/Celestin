"""Deterministic stand-in for the navigation model. Unit tests only; it is not an LLM."""

from __future__ import annotations

import json
import re


class FakeLLM:
    """Selects outline lines whose section path contains one of ``want`` (case-insensitive)."""

    def __init__(self, want=(), reply=None, error=None):
        self.want = [w.lower() for w in want]
        self.reply = reply
        self.error = error
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.error:
            raise self.error
        if self.reply is not None:
            return self.reply
        refs = []
        for line in prompt.splitlines():
            m = re.match(r"(S\d+) \| (.*?) \| (.*?) \|", line)
            if m and any(w in m.group(3).lower() for w in self.want):
                refs.append(m.group(1))
        return json.dumps({"thinking": "fake", "sections": refs})


DOC = """Intro text before any heading.

# Storage Guide

Overview of storage.

## Database choice

We chose SQLite because it needs no server and keeps deployment simple.

## Backups

Copy the database file nightly.

```
# not a heading
```

# Security

## Authentication

Tokens are checked on every call.
"""
