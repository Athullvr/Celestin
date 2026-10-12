"""Live navigation-model check. Opt-in; sends outline text to the provider and costs money.

    CELESTIN_RUN_LLM_TESTS=1 CELESTIN_PAGEINDEX_MODEL=<litellm model> <provider key env> \
        python -m pytest tests/pageindex/test_live_llm.py
"""

import os

import pytest

pytest.importorskip("litellm")
pytestmark = pytest.mark.skipif(
    os.environ.get("CELESTIN_RUN_LLM_TESTS") != "1" or not os.environ.get("CELESTIN_PAGEINDEX_MODEL"),
    reason="set CELESTIN_RUN_LLM_TESTS=1 and CELESTIN_PAGEINDEX_MODEL",
)

from orbit.pageindex.backend import PageIndexBackend
from orbit.pageindex.navigator import LLMTreeNavigator, litellm_chat
from orbit.pageindex.store import PageIndexStore
from tests.pageindex.test_navigation_integration import sections


def test_live_model_selects_the_database_section(tmp_path):
    with PageIndexStore(tmp_path / "d.db") as store:
        store.upsert_document("p", "guide.md", None, "src", "guide", sections(), "t1")
    backend = PageIndexBackend(
        tmp_path / "d.db", LLMTreeNavigator(litellm_chat(os.environ["CELESTIN_PAGEINDEX_MODEL"]))
    )
    chosen = backend.retrieve("p", "Why did we pick SQLite for storage?")
    assert chosen and chosen[0].node_id == "0002"
