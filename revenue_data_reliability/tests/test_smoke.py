"""Smoke tests for Batch 1 UI skeleton."""

import uuid

from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_routes_render():
    for path in ["/", "/exceptions", "/exceptions/1", "/runs", "/runs/1", "/scenarios", "/audit", "/observability"]:
        r = client.get(path)
        assert r.status_code == 200, path


def test_persona_persists():
    c = TestClient(app)
    c.post("/persona", data={"persona_id": "manager"}, follow_redirects=False)
    r = c.get("/")
    assert "FP&amp;A Manager" in r.text or "Manager" in r.text


def test_htmx_post_message():
    c = TestClient(app)
    r = c.post("/threads/analysis/kpi-revenue/messages", data={"content": "smoke msg"})
    assert r.status_code == 200
    assert "smoke msg" in r.text


def test_exceptions_status_filter_and_trend():
    from backend.db import init_pool
    from backend.services import exceptions as exc_svc
    from backend.services import runs as runs_svc

    init_pool()
    trace_id = uuid.uuid4().hex
    run_id = runs_svc.create_run("baseline_run", "test", trace_id)

    try:
        # Insert a controlled set of exceptions for this isolated run.
        from backend.db.connection import execute

        execute(
            """
            INSERT INTO exceptions (run_id, type, severity, period, title, status, trace_id)
            VALUES (%s, 'validation', 'high', '2024-01', 'Old issue', 'resolved', %s),
                   (%s, 'validation', 'critical', '2024-02', 'Old issue 2', 'resolved', %s),
                   (%s, 'validation', 'medium', '2028-12', 'Current issue', 'open', %s),
                   (%s, 'reconciliation', 'medium', '2028-12', 'Current recon', 'open', %s)
            """,
            (run_id, trace_id, run_id, trace_id, run_id, trace_id, run_id, trace_id),
        )

        open_exc = exc_svc.list_exceptions("open", run_id=run_id)
        resolved_exc = exc_svc.list_exceptions("resolved", run_id=run_id)
        all_exc = exc_svc.list_exceptions("all", run_id=run_id)

        assert len(open_exc) == 2, open_exc
        assert len(resolved_exc) == 2, resolved_exc
        assert len(all_exc) == 4

        # Only non-resolved rows are open by default; the service caps the
        # list at 50 rows per page so multiple scenarios don't render unbounded.
        default_open = exc_svc.list_exceptions()
        assert all(e["status"] != "resolved" for e in default_open)
        assert len(default_open) <= 50
    finally:
        runs_svc.delete_run(run_id)