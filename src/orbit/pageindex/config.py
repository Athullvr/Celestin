"""Opt-in PageIndex configuration.

Environment variables:
    CELESTIN_PAGEINDEX             enable document retrieval in retrieve_context (1/true/yes/on)
    CELESTIN_PAGEINDEX_MODEL       LiteLLM model name used to navigate outlines (required to enable)
    CELESTIN_PAGEINDEX_DB_PATH     document index file (default: <database path>.pageindex.db)
    CELESTIN_PAGEINDEX_TIMEOUT     seconds per model call (default 30)
    CELESTIN_PAGEINDEX_MAX_SECTIONS  sections returned per query (default 5)
    CELESTIN_PAGEINDEX_MAX_OUTLINE   largest outline sent to the model (default 400 sections)

The outline (section paths and opening text) and the query are sent to the
configured model provider for every routed query. Provider credentials use
LiteLLM's own environment variables and are never stored by Celestin.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from orbit.database import engine

from .backend import PageIndexBackend
from .errors import PageIndexUnavailable
from .navigator import LLMTreeNavigator, litellm_chat

_TRUE = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class PageIndexSettings:
    enabled: bool
    model: str | None
    store_path: Path
    timeout: float
    max_sections: int
    max_outline: int


def _number(name: str, default: float, cast):
    raw = os.environ.get(name)
    try:
        value = cast(raw) if raw else default
    except ValueError:
        raise ValueError(f"{name} must be a number") from None
    if value <= 0:
        raise ValueError(f"{name} must be positive")
    return value


def load_settings(db_path: str | Path | None = None) -> PageIndexSettings:
    env = os.environ
    database = engine._resolve_path(db_path)
    return PageIndexSettings(
        enabled=env.get("CELESTIN_PAGEINDEX", "").strip().lower() in _TRUE,
        model=env.get("CELESTIN_PAGEINDEX_MODEL") or None,
        store_path=Path(env.get("CELESTIN_PAGEINDEX_DB_PATH") or f"{database}.pageindex.db"),
        timeout=_number("CELESTIN_PAGEINDEX_TIMEOUT", 30.0, float),
        max_sections=_number("CELESTIN_PAGEINDEX_MAX_SECTIONS", 5, int),
        max_outline=_number("CELESTIN_PAGEINDEX_MAX_OUTLINE", 400, int),
    )


def build_pageindex_backend(db_path: str | Path | None = None) -> PageIndexBackend | None:
    """None when disabled; an 'unavailable' backend (with the reason) when enabled but unusable."""
    try:
        settings = load_settings(db_path)
    except ValueError as exc:
        return PageIndexBackend.unavailable(str(exc))
    if not settings.enabled:
        return None
    if not settings.model:
        return PageIndexBackend.unavailable("CELESTIN_PAGEINDEX_MODEL is not set")
    try:
        navigator = LLMTreeNavigator(
            litellm_chat(settings.model, timeout=settings.timeout), max_outline=settings.max_outline
        )
    except PageIndexUnavailable as exc:
        return PageIndexBackend.unavailable(str(exc))
    return PageIndexBackend(settings.store_path, navigator, max_sections=settings.max_sections)
