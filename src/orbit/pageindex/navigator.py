"""LLM navigation of a document outline (the PageIndex retrieval idea).

The model sees only an outline (section path plus a short snippet), never full
text, and answers with outline references. Unknown references are discarded, so
the model cannot invent a source.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable, Protocol, Sequence

from .errors import PageIndexUnavailable

SNIPPET_CHARS = 200


@dataclass(frozen=True, slots=True)
class OutlineEntry:
    doc_key: str
    node_id: str
    path: tuple[str, ...]
    snippet: str


class TreeNavigator(Protocol):
    def select(self, query: str, outline: Sequence[OutlineEntry], limit: int) -> list[tuple[str, str]]:
        """Return up to ``limit`` ``(doc_key, node_id)`` pairs from ``outline``, best first."""


PROMPT = """You are navigating the table of contents of project documents to find the sections \
that answer a question.

Question: {query}

Outline (one section per line: reference | document | section path | opening text):
{outline}

Choose at most {limit} sections most likely to contain the answer, best first. Prefer specific \
sections over broad ones. If nothing is relevant, choose none.
Reply with JSON only: {{"thinking": "<brief reasoning>", "sections": ["S3", "S7"]}}"""


def _one_line(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


class LLMTreeNavigator:
    def __init__(self, llm: Callable[[str], str], *, max_outline: int = 400) -> None:
        self._llm = llm
        self._max_outline = max_outline
        self.last_prompt_chars = 0
        self.last_usage: dict | None = None

    def estimate_prompt_tokens(self, outline: Sequence[OutlineEntry]) -> int:
        """Rough prompt size (4 characters per token); an estimate, not provider-counted."""
        return len(self.build_prompt("", outline, 1)) // 4

    @staticmethod
    def build_prompt(query: str, outline: Sequence[OutlineEntry], limit: int) -> str:
        lines = [
            f"S{i} | {e.doc_key} | {' > '.join(e.path)} | {_one_line(e.snippet)[:SNIPPET_CHARS]}"
            for i, e in enumerate(outline, start=1)
        ]
        return PROMPT.format(query=_one_line(query), outline="\n".join(lines), limit=limit)

    def select(self, query: str, outline: Sequence[OutlineEntry], limit: int) -> list[tuple[str, str]]:
        self.last_prompt_chars = 0
        self.last_usage = None
        if len(outline) > self._max_outline:
            raise PageIndexUnavailable(
                f"outline has {len(outline)} sections (limit {self._max_outline}); "
                "index fewer documents or raise CELESTIN_PAGEINDEX_MAX_OUTLINE"
            )
        prompt = self.build_prompt(query, outline, limit)
        self.last_prompt_chars = len(prompt)
        try:
            reply = self._llm(prompt)
            self.last_usage = getattr(self._llm, "last_usage", None)
        except PageIndexUnavailable:
            raise
        except Exception as exc:
            raise PageIndexUnavailable(f"navigation model call failed: {type(exc).__name__}") from exc
        return self.parse(reply, outline, limit)

    @staticmethod
    def parse(reply: str, outline: Sequence[OutlineEntry], limit: int) -> list[tuple[str, str]]:
        match = re.search(r"\{.*\}", reply or "", re.DOTALL)
        try:
            refs = json.loads(match.group(0))["sections"] if match else None
        except (ValueError, KeyError, TypeError):
            refs = None
        if not isinstance(refs, list):
            raise PageIndexUnavailable("navigation model returned an unparseable reply")
        chosen: list[tuple[str, str]] = []
        for ref in refs:
            m = re.fullmatch(r"S(\d+)", str(ref).strip())
            if not m or not 1 <= int(m.group(1)) <= len(outline):
                continue
            entry = outline[int(m.group(1)) - 1]
            pair = (entry.doc_key, entry.node_id)
            if pair not in chosen:
                chosen.append(pair)
        return chosen[:limit]


class _Chat:
    """Single chat call through LiteLLM; exposes provider-reported token usage after each call."""

    def __init__(self, litellm, model: str, timeout: float, retries: int) -> None:
        self._litellm = litellm
        self._model = model
        self._timeout = timeout
        self._attempts = 1 + max(0, retries)
        self.last_usage: dict | None = None

    def __call__(self, prompt: str) -> str:
        self.last_usage = None
        last_error: Exception | None = None
        for _ in range(self._attempts):
            try:
                response = self._litellm.completion(
                    model=self._model,
                    messages=[{"role": "user", "content": prompt}],
                    timeout=self._timeout,
                    max_retries=0,
                    temperature=0,
                    drop_params=True,
                )
            except Exception as exc:
                if getattr(exc, "status_code", None) in {400, 401, 403, 404}:
                    raise  # misconfiguration or oversized prompt: retrying cannot help
                last_error = exc
                continue
            usage = getattr(response, "usage", None)
            if usage is not None:
                self.last_usage = {
                    "prompt_tokens": getattr(usage, "prompt_tokens", None),
                    "completion_tokens": getattr(usage, "completion_tokens", None),
                }
            return response.choices[0].message.content or ""
        raise last_error  # type: ignore[misc]


def litellm_chat(model: str, *, timeout: float = 30.0, retries: int = 0) -> Callable[[str], str]:
    """A bounded chat call through LiteLLM (installed with the ``pageindex`` extra).

    ``retries`` extra attempts are made only for transient failures (default none).
    Provider credentials come from LiteLLM's standard environment variables
    (for example ``OPENAI_API_KEY``); nothing is stored by Celestin.
    """
    try:
        import litellm
    except ImportError as exc:
        raise PageIndexUnavailable(
            "litellm is not installed; run: pip install 'celestin-memory[pageindex]'"
        ) from exc
    return _Chat(litellm, model, timeout, retries)


def missing_credentials(model: str) -> list[str]:
    """Environment variables LiteLLM says are missing for ``model`` (empty when none or unknown)."""
    try:
        import litellm

        check = litellm.validate_environment(model=model)
    except Exception:
        return []
    return [] if check.get("keys_in_environment") else list(check.get("missing_keys") or [])
