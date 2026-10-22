"""Integration test for pipeline happy path (R2 mocked)."""

import uuid
from unittest.mock import MagicMock

import pytest

from backend.db.connection import execute, fetch_one
from backend.services import orchestrator
from backend.services import runs as runs_svc


@pytest.fixture(autouse=True)
def mock_duckdb(monkeypatch):
    fake_conn = MagicMock()
    monkeypatch.setattr("backend.services.orchestrator.open_connection", lambda: fake_conn)
    monkeypatch.setattr("backend.storage.duckdb_client.query_dicts_on", lambda *a, **k: [])
    # Avoid DE/FA hitting the DB for exceptions; log one action each.
    def _de(run_id, trace_id):
        orchestrator._log_action("de", "remediation_proposal", "run", str(run_id), trace_id, {})

    def _fa(run_id, trace_id):
        orchestrator._log_action("fa", "financial_impact", "run", str(run_id), trace_id, {})

    monkeypatch.setattr("backend.teams.de.DEAgent.propose_remediation_for_run", lambda self, run_id, trace_id: _de(run_id, trace_id) or 0)
    monkeypatch.setattr("backend.teams.fa.FAAgent.quantify_impact_for_run", lambda self, run_id, trace_id: _fa(run_id, trace_id) or 0)
    return fake_conn


def test_pipeline_happy_path():
    trace_id = uuid.uuid4().hex
    execute(
        "INSERT INTO runs (scenario_name, status, trace_id) VALUES (%s, %s, %s)",
        ("baseline_run", "pending", trace_id),
    )
    row = fetch_one("SELECT run_id FROM runs WHERE trace_id = %s", (trace_id,))
    run_id = row["run_id"]

    orchestrator.run_pipeline(run_id)

    run = runs_svc.get_run(run_id)
    assert run["status"] == "completed"

    from backend.db.connection import fetch_all

    actions = fetch_all("SELECT agent_id FROM agent_actions WHERE trace_id = %s", (trace_id,))
    agent_ids = {a["agent_id"] for a in actions}
    assert {"orchestrator", "dq", "de", "fa"}.issubset(agent_ids)

    # cleanup
    execute("DELETE FROM agent_actions WHERE trace_id = %s", (trace_id,))
    execute("DELETE FROM messages WHERE trace_id = %s", (trace_id,))
    execute("DELETE FROM runs WHERE trace_id = %s", (trace_id,))