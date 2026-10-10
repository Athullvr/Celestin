"""Runnable usage example for Members 2 and 3.

Run with:
    python -m docs.examples.usage_example
"""

from orbit.database.engine import connect
from orbit.repositories import (
    ChatMessageRepository,
    DecisionRepository,
)


def main() -> None:
    conn = connect(":memory:")  # omit the arg to use the default database
    messages = ChatMessageRepository(conn)
    decisions = DecisionRepository(conn)

    # 1. Persist raw chat history.
    msg_id = messages.insert(
        project="demo",
        conversation_id="conv-1",
        role="user",
        content="Adopt bcrypt for password hashing.",
    )
    print(f"stored message id={msg_id}")

    # 2. Promote a chat message into a canonical decision, keeping provenance.
    decision = decisions.save(
        project="demo",
        key="password-hashing",
        value="Use bcrypt (cost >= 12) for all new passwords.",
        source_message_id=msg_id,
        status="draft",
    )
    print(f"decision saved: {decision}")

    # 3. Review workflow: draft -> approved.
    decision = decisions.update_status("demo", "password-hashing", "approved")
    print(f"status now: {decision['status']}")

    # 4. Project-scoped reads.
    convo = messages.list_for_conversation("demo", "conv-1")
    live = decisions.list_for_project("demo", include_deprecated=False)
    print(f"{len(convo)} message(s), {len(live)} live decision(s)")

    conn.close()


if __name__ == "__main__":
    main()
