"""Impact column and Manager rejection-loop tests."""
import uuid

from fastapi.testclient import TestClient

from backend.db.connection import execute, fetch_one, init_pool
from backend.main import app
from backend.services import exceptions as exc_svc
from backend.services import reconciliations as recon_svc
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
        exception_id = _make_exception(run_id, trace_id, status="awaiting_approval")
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
        c.post("/persona", data={"persona_id": "manager"}, follow_redirects=False)

        missing = c.post(f"/exceptions/{exception_id}/reject", data={"reason": ""})
        assert missing.status_code == 400

        response = c.post(
            f"/exceptions/{exception_id}/reject",
            data={"reason": "Missed rows"},
            follow_redirects=False,
        )
        assert response.status_code == 303

        updated = exc_svc.get_exception(exception_id)
        assert updated["status"] == "awaiting_approval"
        assert updated["remediation_attempts"] == 2

        from backend.services import messages

        thread = messages.get_messages("exception", str(exception_id))
        assert any("Missed rows" in m["content"] for m in thread)
    finally:
        runs_svc.delete_run(run_id)
def test_reconciliation_exception_uses_rule_metadata():
    init_pool()
    run_id, trace_id = _make_run()
    try:
        rows = [
            {
                "period": "2026-01",
                "account_id": "1",
                "item_category": "Electronics",
                "billings": 100.0,
                "gl": 94.0,
                "variance_pct": 0.06,
            }
        ]
        recon_svc.persist_reconciliation(run_id, rows, trace_id, latest_period="2026-01")
        exc = fetch_one(
            "SELECT title, severity, details FROM exceptions "
            "WHERE run_id = %s AND rule_id = 'VAL_RECON_BILLINGS_GL'",
            (run_id,),
        )
        rule = val_svc.get_rule("VAL_RECON_BILLINGS_GL")
        assert exc["title"] == "Billings vs General Ledger variance"
        assert exc["severity"] == rule["severity"]
        assert "Worst variance" in exc["details"]["summary"]
    finally:
        runs_svc.delete_run(run_id)


def test_exceptions_default_to_open_without_banner():
    init_pool()
    run_id, trace_id = _make_run()
    try:
        open_id = _make_exception(run_id, trace_id, status="open")
        hist_id = _make_exception(run_id, trace_id, status="resolved")
        c = TestClient(app)
        r = c.get(f"/exceptions?run_id={run_id}")
        assert r.status_code == 200
        assert f'href="/exceptions/{open_id}"' in r.text
        assert f'href="/exceptions/{hist_id}"' not in r.text
        assert "Showing Open issues." not in r.text

        r_all = c.get(f"/exceptions?run_id={run_id}&status=all")
        assert f'href="/exceptions/{open_id}"' in r_all.text
        assert f'href="/exceptions/{hist_id}"' in r_all.text
    finally:
        runs_svc.delete_run(run_id)


def test_approve_transitions_through_approved(monkeypatch):
    init_pool()
    run_id, trace_id = _make_run()
    try:
        exception_id = _make_exception(run_id, trace_id, status="awaiting_approval")
        seen = []

        from backend.teams import de as de_team

        def fake_execute(self, exc, trace_id):
            row = fetch_one(
                "SELECT status FROM exceptions WHERE exception_id = %s",
                (exception_id,),
            )
            seen.append(row["status"])

        monkeypatch.setattr(de_team.DEAgent, "execute_remediation", fake_execute)

        c = TestClient(app)
        c.post("/persona", data={"persona_id": "manager"}, follow_redirects=False)
        response = c.post(f"/exceptions/{exception_id}/approve", follow_redirects=False)
        assert response.status_code == 303
        assert seen == ["approved"]
        assert exc_svc.get_exception(exception_id)["status"] == "approved"
    finally:
        runs_svc.delete_run(run_id)

def test_financial_impact_fallback_uses_rule_impact(monkeypatch):
    init_pool()
    run_id, trace_id = _make_run()
    try:
        exception_id = _make_exception(run_id, trace_id)
        exc = exc_svc.get_exception(exception_id)

        from backend.teams import fa

        monkeypatch.setattr(
            fa.llm_client,
            "call_llm",
            lambda *a, **k: fa.llm_client._template_fallback("prompt"),
        )
        fa.FinancialImpactAgent().quantify_impact(exc, trace_id)

        updated = exc_svc.get_exception(exception_id)
        assert updated["impact"] == "overstates revenue"
        from backend.services import messages

        thread = messages.get_messages("exception", str(exception_id))
        assert any("Financial impact: overstates revenue." in m["content"] for m in thread)
        assert all("Agent task received" not in m["content"] for m in thread)
    finally:
        runs_svc.delete_run(run_id)


def test_de_fallback_posts_structured_proposal(monkeypatch):
    init_pool()
    run_id, trace_id = _make_run()
    try:
        exception_id = _make_exception(run_id, trace_id)
        exc = exc_svc.get_exception(exception_id)

        from backend.teams import de as de_team

        monkeypatch.setattr(
            de_team.llm_client,
            "call_llm",
            lambda *a, **k: de_team.llm_client._template_fallback("prompt"),
        )
        de_team.DEAgent().propose_remediation(exc, trace_id)

        updated = exc_svc.get_exception(exception_id)
        assert updated["status"] == "awaiting_approval"
        from backend.services import messages

        thread = messages.get_messages("exception", str(exception_id))
        content = thread[-1]["content"]
        assert "Proposed Action:" in content
        assert "Quarantine 2 record(s)" in content
        assert "Agent task received" not in content
    finally:
        runs_svc.delete_run(run_id)

def test_request_remediation_triggers_de_for_one_exception(monkeypatch):
    init_pool()
    run_id, trace_id = _make_run()
    try:
        exception_id = _make_exception(run_id, trace_id, status="open")
        called = []

        from backend.teams import de as de_team

        def fake_propose(self, exc, trace_id, rejection_reason=None):
            called.append(exc.get("id", exc.get("exception_id")))
            execute(
                "UPDATE exceptions SET status = 'awaiting_approval' WHERE exception_id = %s",
                (exception_id,),
            )
            return {}

        monkeypatch.setattr(de_team.DEAgent, "propose_remediation", fake_propose)

        c = TestClient(app)
        c.post("/persona", data={"persona_id": "manager"}, follow_redirects=False)
        response = c.post(
            f"/exceptions/{exception_id}/request-fix",
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert called == [exception_id]
        assert exc_svc.get_exception(exception_id)["status"] == "awaiting_approval"
    finally:
        runs_svc.delete_run(run_id)


def test_reject_presets_are_rule_specific():
    init_pool()
    run_id, trace_id = _make_run()
    try:
        exception_id = _make_exception(run_id, trace_id, rule_id="VAL_FK_CUSTOMER_EXISTS")
        c = TestClient(app)
        r = c.get(f"/exceptions/{exception_id}")
        assert "Fix source mapping" in r.text
        assert "Quarantine affected rows" not in r.text
        assert "Select an action or type instructions." in r.text
    finally:
        runs_svc.delete_run(run_id)

def test_dismiss_as_false_positive_sets_terminal_status(monkeypatch):
    init_pool()
    run_id, trace_id = _make_run()
    try:
        exception_id = _make_exception(run_id, trace_id, status="awaiting_approval")
        from backend.teams import de as de_team

        called = []
        monkeypatch.setattr(
            de_team.DEAgent,
            "propose_remediation",
            lambda self, *a, **k: called.append(True) or {},
        )

        c = TestClient(app)
        c.post("/persona", data={"persona_id": "manager"}, follow_redirects=False)
        response = c.post(
            f"/exceptions/{exception_id}/reject",
            data={"reason": "Dismiss as false positive"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert exc_svc.get_exception(exception_id)["status"] == "dismissed"
        assert called == []
    finally:
        runs_svc.delete_run(run_id)
