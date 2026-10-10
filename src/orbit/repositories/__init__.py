"""Repository operations for chat messages and canonical project decisions.

This is the public persistence API for Members 2 (vector index) and 3
(MCP tools). All functions are project-scoped, validate their inputs, and
use parameterized SQL exclusively.

Module-level functions operate on the default, library-owned connection
(the process-wide database at ``DB_PATH``). Use
:func:`orbit.repositories.messages.ingest_chat_message` /
``...decision`).save_decision`` for the default store, or instantiate
``ChatMessageRepository`` / ``DecisionRepository`` with your own
connection when embedding the layer elsewhere.
"""

from orbit.repositories.decisions import DecisionRepository, save_decision
from orbit.repositories.messages import ChatMessageRepository, ingest_chat_message

__all__ = [
    "ChatMessageRepository",
    "DecisionRepository",
    "ingest_chat_message",
    "save_decision",
]
