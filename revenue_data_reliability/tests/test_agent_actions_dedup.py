"""Tests for agent_actions dedup / trace sharing."""


def test_agent_action_trace_shared():
    import uuid

    from backend.db.connection import execute, fetch_all
    from backend.services import dq

    trace_id = uuid.uuid4().hex
    run_id = 1
    results = [{"rule_id": "R1", "status": "pass", "summary_count": 0}]
    dq.post_validation_summary(run_id, results, trace_id=trace_id)

    rows = fetch_all(
        "SELECT * FROM agent_actions WHERE trace_id = %s", (trace_id,)
    )
    assert len(rows) == 1
    assert rows[0]["agent_id"] == "dq"

    # cleanup
    execute("DELETE FROM agent_actions WHERE trace_id = %s", (trace_id,))
    execute("DELETE FROM messages WHERE trace_id = %s", (trace_id,))