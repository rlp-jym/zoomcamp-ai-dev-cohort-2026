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
    # The pipeline's first step downloads the local Parquet cache.  This test
    # exercises orchestration only, so keep it off the network.
    monkeypatch.setattr("backend.services.orchestrator.ensure_local_scenario", lambda *a, **k: None)
    monkeypatch.setattr("backend.services.validations.ensure_local_scenario", lambda *a, **k: None)
    monkeypatch.setattr("backend.services.reconciliations.ensure_local_scenario", lambda *a, **k: None)
    # Avoid the Financial Impact Agent hitting the DB; log one action.
    def _fa(run_id, trace_id):
        orchestrator._log_action("fa", "financial_impact", "run", str(run_id), trace_id, {})

    monkeypatch.setattr("backend.teams.fa.FinancialImpactAgent.quantify_impact_for_run", lambda self, run_id, trace_id: _fa(run_id, trace_id) or 0)
    return fake_conn


def test_pipeline_happy_path():
    trace_id = uuid.uuid4().hex
    execute(
        "INSERT INTO runs (dataset_name, status, trace_id) VALUES (%s, %s, %s)",
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
    assert {"orchestrator", "dq", "fa"}.issubset(agent_ids)
    assert "de" not in agent_ids

    # cleanup
    execute("DELETE FROM agent_actions WHERE trace_id = %s", (trace_id,))
    execute("DELETE FROM messages WHERE trace_id = %s", (trace_id,))
    execute("DELETE FROM runs WHERE trace_id = %s", (trace_id,))


def test_pipeline_uses_four_progress_stages(monkeypatch):
    updates = []
    real_update = runs_svc.update_run

    def record_update(run_id, **fields):
        if fields.get("current_stage"):
            updates.append((fields["current_stage"], fields.get("progress_percent")))
        return real_update(run_id, **fields)

    monkeypatch.setattr(runs_svc, "update_run", record_update)

    trace_id = uuid.uuid4().hex
    execute(
        "INSERT INTO runs (dataset_name, status, trace_id) VALUES (%s, %s, %s)",
        ("baseline_run", "pending", trace_id),
    )
    row = fetch_one("SELECT run_id FROM runs WHERE trace_id = %s", (trace_id,))
    run_id = row["run_id"]
    try:
        orchestrator.run_pipeline(run_id)
        assert updates[:4] == [
            ("Validation", 25),
            ("Reconciliation", 50),
            ("Discussion", 75),
            ("Complete", 100),
        ]
    finally:
        runs_svc.delete_run(run_id)

