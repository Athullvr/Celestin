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

    def select(self, query: str, outline: Sequence[OutlineEntry], limit: int) -> list[tuple[str, str]]:
        if len(outline) > self._max_outline:
            raise PageIndexUnavailable(
                f"outline has {len(outline)} sections (limit {self._max_outline}); "
                "index fewer documents or raise CELESTIN_PAGEINDEX_MAX_OUTLINE"
            )
        lines = [
            f"S{i} | {e.doc_key} | {' > '.join(e.path)} | {_one_line(e.snippet)[:SNIPPET_CHARS]}"
            for i, e in enumerate(outline, start=1)
        ]
        prompt = PROMPT.format(query=_one_line(query), outline="\n".join(lines), limit=limit)
        try:
            reply = self._llm(prompt)
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


def litellm_chat(model: str, *, timeout: float = 30.0) -> Callable[[str], str]:
    """A single-attempt chat call through LiteLLM (installed with the ``pageindex`` extra).

    Provider credentials come from LiteLLM's standard environment variables
    (for example ``OPENAI_API_KEY``); nothing is stored by Celestin.
    """
    try:
        import litellm
    except ImportError as exc:
        raise PageIndexUnavailable(
            "litellm is not installed; run: pip install 'celestin-memory[pageindex]'"
        ) from exc

    def chat(prompt: str) -> str:
        response = litellm.completion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            timeout=timeout,
            max_retries=0,
            temperature=0,
            drop_params=True,
        )
        return response.choices[0].message.content or ""

    return chat
