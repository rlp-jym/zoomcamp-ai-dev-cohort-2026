"""Smoke tests for Batch 1 UI skeleton."""

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
    from backend.db import fetch_one, init_pool
    from backend.services import exceptions as exc_svc

    init_pool()
    run = fetch_one("SELECT run_id FROM runs ORDER BY run_id DESC LIMIT 1")
    assert run is not None
    run_id = run["run_id"]

    # Insert a controlled set of exceptions for this run.
    from backend.db.connection import execute

    execute(
        "DELETE FROM exceptions WHERE run_id = %s AND trace_id = 'test-lifecycle'",
        (run_id,),
    )
    execute(
        """
        INSERT INTO exceptions (run_id, type, severity, period, title, status, trace_id)
        VALUES (%s, 'validation', 'high', '2024-01', 'Old issue', 'resolved', 'test-lifecycle'),
               (%s, 'validation', 'critical', '2024-02', 'Old issue 2', 'resolved', 'test-lifecycle'),
               (%s, 'validation', 'medium', '2028-12', 'Current issue', 'open', 'test-lifecycle'),
               (%s, 'reconciliation', 'medium', '2028-12', 'Current recon', 'open', 'test-lifecycle')
        """,
        (run_id, run_id, run_id, run_id),
    )

    open_exc = exc_svc.list_exceptions("open")
    resolved_exc = exc_svc.list_exceptions("resolved")
    all_exc = exc_svc.list_exceptions("all")

    test_open = [e for e in open_exc if e["trace_id"] == "test-lifecycle"]
    test_resolved = [e for e in resolved_exc if e["trace_id"] == "test-lifecycle"]
    assert len(test_open) == 2, test_open
    assert len(test_resolved) == 2, test_resolved
    assert len(all_exc) >= 4

    # Only non-resolved rows are open by default; the service caps the list
    # at 50 rows per page so multiple scenarios don't render unbounded.
    default_open = exc_svc.list_exceptions()
    assert all(e["status"] != "resolved" for e in default_open)
    assert len(default_open) <= 50

    # Cleanup.
    execute("DELETE FROM exceptions WHERE trace_id = 'test-lifecycle'")