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


def _make_run(scenario=None):
    trace_id = uuid.uuid4().hex
    row = fetch_one(
        """
        INSERT INTO runs (dataset_name, status, triggered_by, trace_id,
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


def test_reject_route_is_removed():
    init_pool()
    run_id, trace_id = _make_run()
    try:
        exception_id = _make_exception(run_id, trace_id, status="awaiting_approval")
        c = TestClient(app)
        c.post("/persona", data={"persona_id": "manager"}, follow_redirects=False)
        response = c.post(f"/exceptions/{exception_id}/reject", data={"reason": "Missed rows"})
        assert response.status_code == 404
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

        def fake_quarantine(self, exc, trace_id):
            row = fetch_one(
                "SELECT status FROM exceptions WHERE exception_id = %s",
                (exception_id,),
            )
            seen.append(row["status"])
            return (1, 0)

        monkeypatch.setattr(de_team.DEAgent, "execute_quarantine", fake_quarantine)

        c = TestClient(app)
        c.post("/persona", data={"persona_id": "manager"}, follow_redirects=False)
        response = c.post(f"/exceptions/{exception_id}/approve", follow_redirects=False)
        assert response.status_code == 303
        assert seen == ["approved"]
        assert exc_svc.get_exception(exception_id)["status"] == "resolved"
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


def test_awaiting_approval_has_only_quarantine_or_dismiss():
    init_pool()
    run_id, trace_id = _make_run()
    try:
        exception_id = _make_exception(
            run_id, trace_id, rule_id="VAL_FK_CUSTOMER_EXISTS", status="awaiting_approval"
        )
        c = TestClient(app)
        r = c.get(f"/exceptions/{exception_id}")
        assert "Execute Fix (Quarantine)" in r.text
        assert "Dismiss (False Positive)" in r.text
        assert "Request Revision" not in r.text
        assert 'name="reason"' not in r.text
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
            f"/exceptions/{exception_id}/dismiss",
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert exc_svc.get_exception(exception_id)["status"] == "dismissed"
        assert called == []
    finally:
        runs_svc.delete_run(run_id)

def test_scenario_and_persona_labels():
    from backend.templating import persona_label, scenario_label

    assert scenario_label("generated_seed5_y5") == "Seed 5 (Year 5)"
    assert scenario_label("baseline_run") == "Baseline Run"
    assert persona_label("analyst") == "FP&A Analyst"
    assert persona_label("de") == "Data Engineer"


def test_decision_layout_is_state_driven():
    init_pool()
    run_id, trace_id = _make_run()
    try:
        exception_id = _make_exception(run_id, trace_id, status="open")
        c = TestClient(app)
        c.post("/persona", data={"persona_id": "manager"}, follow_redirects=False)

        open_page = c.get(f"/exceptions/{exception_id}")
        assert "Request Remediation" in open_page.text
        assert "Execute Fix (Quarantine)" not in open_page.text
        assert "Dismiss (False Positive)" not in open_page.text

        execute(
            "UPDATE exceptions SET status = 'awaiting_approval' WHERE exception_id = %s",
            (exception_id,),
        )
        awaiting_page = c.get(f"/exceptions/{exception_id}")
        assert "Execute Fix (Quarantine)" in awaiting_page.text
        assert "Dismiss (False Positive)" in awaiting_page.text
        assert "Request Revision" not in awaiting_page.text
        assert ">Approve</button>" not in awaiting_page.text
    finally:
        runs_svc.delete_run(run_id)


def test_dismissed_and_resolved_leave_open_queue():
    init_pool()
    run_id, trace_id = _make_run()
    try:
        open_id = _make_exception(run_id, trace_id, status="open")
        dismissed_id = _make_exception(run_id, trace_id, status="dismissed")
        resolved_id = _make_exception(run_id, trace_id, status="resolved")
        open_ids = {e["id"] for e in exc_svc.list_exceptions("open", run_id=run_id)}
        assert open_id in open_ids
        assert dismissed_id not in open_ids
        assert resolved_id not in open_ids
    finally:
        runs_svc.delete_run(run_id)


def test_publish_gate_blocks_open_data_issues():
    init_pool()
    dataset = f"test_publish_gate_{uuid.uuid4().hex[:8]}"
    execute("INSERT INTO datasets (name, status, seed, table_count) VALUES (%s, 'ready', 9, 16)", (dataset,))
    run_id, trace_id = _make_run(scenario=dataset)
    try:
        _make_exception(run_id, trace_id, status="open")
        c = TestClient(app)
        c.post("/persona", data={"persona_id": "manager"}, follow_redirects=False)

        page = c.get(f"/runs/{run_id}")
        assert "Cannot publish: 1 open data issues remain." in page.text
        assert "disabled>Approve Go-Live" in page.text

        blocked = c.post(f"/runs/{run_id}/approve", follow_redirects=False)
        assert blocked.status_code == 400
    finally:
        runs_svc.delete_run(run_id)
        execute("DELETE FROM datasets WHERE name = %s", (dataset,))


def test_publish_refreshes_dashboard_cache(monkeypatch):
    init_pool()
    dataset = f"test_publish_cache_{uuid.uuid4().hex[:8]}"
    execute("INSERT INTO datasets (name, status, seed, table_count) VALUES (%s, 'ready', 9, 16)", (dataset,))
    run_id, _trace_id = _make_run(scenario=dataset)
    try:
        from backend.services import dashboard as dashboard_svc

        calls = []
        monkeypatch.setattr(
            dashboard_svc,
            "invalidate_dashboard_cache",
            lambda name=None: calls.append(("invalidate", name)),
        )
        monkeypatch.setattr(
            dashboard_svc,
            "refresh_dashboard_cache",
            lambda name: calls.append(("refresh", name)) or "updated",
        )

        c = TestClient(app)
        c.post("/persona", data={"persona_id": "manager"}, follow_redirects=False)
        response = c.post(f"/runs/{run_id}/approve", follow_redirects=False)
        assert response.status_code == 303
        assert ("invalidate", dataset) in calls
        assert ("refresh", dataset) in calls
    finally:
        runs_svc.delete_run(run_id)
        execute("DELETE FROM datasets WHERE name = %s", (dataset,))
