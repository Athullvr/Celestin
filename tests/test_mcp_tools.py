from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from mcp.server.fastmcp.exceptions import ToolError

from memory_bridge.mcp_server import server
from memory_bridge.mcp_server import mock_services
from memory_bridge.mcp_server.persistence_services import PersistenceServices
from memory_bridge.mcp_server.server import (
    MAX_TOKEN_BUDGET,
    ingest_chat_message,
    mcp,
    retrieve_context,
    save_decision,
    search_chat_history,
)


class ToolContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        adapter = PersistenceServices(Path(self._temp_dir.name) / "memory.db")
        self._service_patch = patch.object(server, "persistence_services", adapter)
        self._service_patch.start()

    def tearDown(self) -> None:
        self._service_patch.stop()
        self._temp_dir.cleanup()

    def test_all_public_tools_are_registered_once(self) -> None:
        tools = mcp._tool_manager.list_tools()
        names = [tool.name for tool in tools]
        for expected in (
            "ingest_chat_message",
            "save_decision",
            "search_chat_history",
            "retrieve_context",
            "ping",
        ):
            self.assertEqual(names.count(expected), 1)
        schemas = {tool.name: tool.parameters for tool in tools}
        self.assertEqual(set(schemas["ingest_chat_message"]["properties"]), {"project", "conversation_id", "role", "content"})
        self.assertEqual(set(schemas["save_decision"]["properties"]), {"project", "key", "value", "source_message_id"})
        self.assertEqual(set(schemas["search_chat_history"]["properties"]), {"project", "query", "limit"})
        self.assertEqual(set(schemas["retrieve_context"]["properties"]), {"project", "query", "token_budget"})

    def test_fastmcp_registered_tool_is_callable(self) -> None:
        import asyncio

        async def invoke():
            return await mcp._tool_manager.call_tool(
                "ingest_chat_message",
                {"project": "demo", "conversation_id": "conv-1", "role": "user", "content": "hello"},
            )

        result = asyncio.run(invoke())
        self.assertEqual(result["project"], "demo")
        self.assertTrue(result["message_id"].isdigit())

    def test_ingest_shape_and_project_scope(self) -> None:
        result = ingest_chat_message("alpha", "conv-1", "user", "Hello")
        self.assertEqual(set(result), {"project", "message_id", "conversation_id", "role", "content", "created_at"})
        self.assertEqual(result["project"], "alpha")
        self.assertEqual(result["content"], "Hello")
        self.assertTrue(result["message_id"].isdigit())
        self.assertTrue(result["created_at"].endswith("Z"))
        datetime.fromisoformat(result["created_at"].replace("Z", "+00:00"))

    def test_save_decision_is_a_draft(self) -> None:
        message = ingest_chat_message("alpha", "conversation-1", "user", "Use Python")
        result = save_decision("alpha", "runtime", "Python", message["message_id"])
        self.assertEqual(set(result), {"project", "decision_id", "key", "value", "status", "source_message_id", "created_at", "updated_at"})
        self.assertEqual(result["status"], "draft")
        self.assertEqual(result["source_message_id"], message["message_id"])
        self.assertTrue(result["created_at"].endswith("Z"))

    def test_search_shape_and_limit(self) -> None:
        result = search_chat_history("alpha", "hello", 1)
        self.assertEqual(set(result), {"project", "query", "results"})
        self.assertLessEqual(len(result["results"]), 1)
        item = result["results"][0]
        self.assertEqual(set(item), {"message_id", "project", "source_message_id", "conversation_id", "role", "content", "created_at", "score"})

    def test_retrieve_context_shape_and_budget(self) -> None:
        result = retrieve_context("alpha", "hello", MAX_TOKEN_BUDGET)
        self.assertEqual(set(result), {"project", "query", "items", "rendered_context", "token_count", "token_budget", "token_count_is_estimate", "token_counter", "excluded"})
        self.assertLessEqual(result["token_count"], result["token_budget"])
        self.assertTrue(result["token_count_is_estimate"])
        if result["items"]:
            self.assertEqual(set(result["items"][0]), {"record_id", "source_message_id", "created_at", "record_kind", "status", "content", "relevance_score"})

    def test_tools_delegate_to_mock_service_module(self) -> None:
        self.assertIsInstance(server.persistence_services, PersistenceServices)
        self.assertTrue(callable(mock_services.search_chat_history))
        self.assertTrue(callable(mock_services.retrieve_context))

    def assert_invalid(self, callback, *args, **kwargs) -> None:
        with self.assertRaises(ToolError) as raised:
            callback(*args, **kwargs)
        payload = json.loads(str(raised.exception))
        self.assertEqual(payload["error"]["code"], "INVALID_ARGUMENT")

    def test_invalid_required_strings_and_role(self) -> None:
        self.assert_invalid(ingest_chat_message, " ", "conv", "user", "text")
        self.assert_invalid(ingest_chat_message, "p", "conv", "function", "text")
        self.assert_invalid(ingest_chat_message, "p", "conv", "user", " \t")
        self.assert_invalid(save_decision, "p", "key", "value", " ")
        self.assert_invalid(search_chat_history, "p", " ")
        self.assert_invalid(retrieve_context, "p", " ", 10)

    def test_invalid_limits_and_token_budgets(self) -> None:
        for limit in (0, 101, True, 1.5):
            self.assert_invalid(search_chat_history, "p", "query", limit)
        for budget in (0, -1, True, 1.5, MAX_TOKEN_BUDGET + 1):
            self.assert_invalid(retrieve_context, "p", "query", budget)


if __name__ == "__main__":
    unittest.main()
