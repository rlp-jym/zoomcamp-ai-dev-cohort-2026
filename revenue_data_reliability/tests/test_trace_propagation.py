"""Tests for trace_id propagation."""


def test_trace_id_stored_on_run():
    import uuid

    from backend.db.connection import execute, fetch_one

    trace_id = uuid.uuid4().hex
    # Insert a minimal run row.
    execute(
        """
        INSERT INTO runs (scenario_name, status, trace_id)
        VALUES (%s, %s, %s)
        """,
        ("baseline_run", "completed", trace_id),
    )
    row = fetch_one("SELECT trace_id FROM runs WHERE trace_id = %s", (trace_id,))
    assert row is not None
    assert row["trace_id"] == trace_id

    execute("DELETE FROM runs WHERE trace_id = %s", (trace_id,))