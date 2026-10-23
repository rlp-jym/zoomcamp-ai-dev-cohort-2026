"""Impact column and Manager rejection-loop tests."""
import uuid

from fastapi.testclient import TestClient

from backend.db.connection import execute, fetch_one, init_pool
from backend.main import app
from backend.services import exceptions as exc_svc
from backend.services import runs as runs_svc
from backend.services import validations as val_svc

client = TestClient(app)


def _make_run(scenario="baseline_run"):
    trace_id = uuid.uuid4().hex
    row = fetch_one(
        """
        INSERT INTO runs (scenario_name, status, triggered_by, trace_id,
                          started_at, finished_at, duration)
        VALUES (%s, 'completed', 'test', %s, now(), now(), '0s')
        RETURNING run_id
        """,
        (scenario, trace_id),
    )
    return row["run_id"], trace_id


def _make_exception(run_id, trace_id, rule_id="VAL_DUPLICATE_INVOICE_LINE", status="open"):
    rule = val_svc.get_rule(rule_id)
    row = fetch_one(
        """
        INSERT INTO exceptions (run_id, type, severity, period, title, status,
                                trace_id, rule_id, details)
        VALUES (%s, 'validation', %s, '2025-01', %s, %s, %s, %s,
                '{"count": 2, "sample": []}'::jsonb)
        RETURNING exception_id
        """,
        (
            run_id,
            rule["severity"],
            val_svc.EXCEPTION_TITLES[rule_id],
            status,
            trace_id,
            rule_id,
        ),
    )
    return row["exception_id"]


def test_rule_default_impacts_are_seeded():
    init_pool()
    from backend.db.seed import RULE_IMPACTS, seed

    seed()
    row = fetch_one("SELECT impact FROM rules WHERE rule_id = 'VAL_DUPLICATE_INVOICE_LINE'")
    assert row["impact"] == "overstates revenue"
    row = fetch_one("SELECT impact FROM rules WHERE rule_id = 'VAL_FX_RATE_EXISTS'")
    assert row["impact"] == "misstates foreign exchange"
    assert RULE_IMPACTS["VAL_DUPLICATE_INVOICE_LINE"] == "overstates revenue"


def test_validation_and_exception_share_base_metadata():
    init_pool()
    run_id, trace_id = _make_run()
    try:
        exception_id = _make_exception(run_id, trace_id)
        execute(
            """
            INSERT INTO validations (run_id, rule_id, status, summary_count, sampled_failures)
            VALUES (%s, 'VAL_DUPLICATE_INVOICE_LINE', 'fail', 2, '[]')
            """,
            (run_id,),
        )
        exc = next(e for e in exc_svc.list_exceptions("all", run_id=run_id) if e["id"] == exception_id)
        val = next(v for v in val_svc.list_validations(run_id) if v["rule_id"] == "VAL_DUPLICATE_INVOICE_LINE")
        assert exc["title"] == val["title"] == "Duplicate invoice lines"
        assert exc["description"] == val["description"]
        assert exc["severity"] == val["severity"]
        assert exc["impact"] == val["impact"] == "overstates revenue"
        assert exc["count"] == val["summary_count"] == 2
    finally:
        runs_svc.delete_run(run_id)


def test_financial_impact_agent_persists_exception_impact(monkeypatch):
    init_pool()
    run_id, trace_id = _make_run()
    try:
        exception_id = _make_exception(run_id, trace_id)
        exc = exc_svc.get_exception(exception_id)

        from backend.teams import fa

        narrative = "Overstates revenue by $50,000 (2.3% of target)."
        monkeypatch.setattr(fa.llm_client, "call_llm", lambda *a, **k: narrative)
        fa.FinancialImpactAgent().quantify_impact(exc, trace_id)

        updated = exc_svc.get_exception(exception_id)
        assert updated["impact"] == narrative
    finally:
        runs_svc.delete_run(run_id)


def test_manager_rejection_requires_reason_and_triggers_de(monkeypatch):
    init_pool()
    run_id, trace_id = _make_run()
    try:
        exception_id = _make_exception(run_id, trace_id, status="remediation_proposed")
        execute(
            "UPDATE exceptions SET remediation_attempts = 1 WHERE exception_id = %s",
            (exception_id,),
        )

        from backend.teams import de as de_team

        monkeypatch.setattr(
            de_team.llm_client,
            "call_llm",
            lambda *a, **k: "Revised proposal addressing: Missed rows.",
        )

        c = TestClient(app)
        c.post("/persona", data={"persona_id": "manager"})

        missing = c.post(f"/exceptions/{exception_id}/reject", data={"reason": ""})
        assert missing.status_code == 400

        response = c.post(
            f"/exceptions/{exception_id}/reject",
            data={"reason": "Missed rows"},
        )
        assert response.status_code == 200

        updated = exc_svc.get_exception(exception_id)
        assert updated["status"] == "remediation_proposed"
        assert updated["remediation_attempts"] == 2

        from backend.services import messages

        thread = messages.get_messages("exception", str(exception_id))
        assert any("Missed rows" in m["content"] for m in thread)
    finally:
        runs_svc.delete_run(run_id)