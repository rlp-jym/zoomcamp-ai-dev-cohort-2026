"""Tests for deferred message/action writes during agent discussion."""

import uuid

from backend.db.connection import execute, fetch_one
from backend.services import messages as msg_svc
from backend.services.write_buffer import buffered_writes
from backend.teams.base import BaseAgent


def test_buffered_writes_defer_and_flush():
    trace_id = uuid.uuid4().hex
    anchor_id = f"test-{trace_id}"
    agent = BaseAgent("de")
    try:
        with buffered_writes() as buffer:
            msg_svc.post_message(
                "run",
                anchor_id,
                agent.persona,
                "buffered message",
                trace_id=trace_id,
            )
            agent.log_action("test_action", "run", anchor_id, trace_id)
            assert len(buffer.messages) == 1
            assert len(buffer.actions) == 1
            messages_before = fetch_one(
                "SELECT COUNT(*) AS c FROM messages WHERE trace_id = %s",
                (trace_id,),
            )
            actions_before = fetch_one(
                "SELECT COUNT(*) AS c FROM agent_actions WHERE trace_id = %s",
                (trace_id,),
            )
            assert messages_before["c"] == 0
            assert actions_before["c"] == 0

        messages_after = fetch_one(
            "SELECT COUNT(*) AS c FROM messages WHERE trace_id = %s",
            (trace_id,),
        )
        actions_after = fetch_one(
            "SELECT COUNT(*) AS c FROM agent_actions WHERE trace_id = %s",
            (trace_id,),
        )
        assert messages_after["c"] == 1
        assert actions_after["c"] == 1
    finally:
        execute("DELETE FROM messages WHERE trace_id = %s", (trace_id,))
        execute("DELETE FROM agent_actions WHERE trace_id = %s", (trace_id,))
        execute(
            "DELETE FROM discussions WHERE anchor_type = 'run' AND anchor_id = %s",
            (anchor_id,),
        )
