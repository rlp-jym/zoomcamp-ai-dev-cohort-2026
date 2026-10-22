"""Validation progress row / HTMX polling tests."""

import uuid

from fastapi.testclient import TestClient

from backend.db.connection import execute, fetch_one
from backend.main import app
from backend.routes import pages
from backend.templating import templates

client = TestClient(app)


def _insert_run(status="running", stage="Reconciliation", pct=40, duration=None):
    trace_id = uuid.uuid4().hex
    row = fetch_one(
        """
        INSERT INTO runs (scenario_name, status, current_stage, progress_percent,
                          started_at, triggered_by, trace_id, duration_seconds)
        VALUES ('baseline_run', %s, %s, %s, now(), 'test', %s, %s)
        RETURNING run_id
        """,
        (status, stage, pct, trace_id, duration),
    )
    return row["run_id"]


def _delete_run(run_id):
    execute("DELETE FROM runs WHERE run_id = %s", (run_id,))


def test_run_row_running_keeps_polling():
    run = {
        "id": 7,
        "scenario": "baseline_run",
        "status": "running",
        "current_stage": "Reconciliation",
        "progress_percent": 40,
        "started_at": "2026-10-23 10:00:00",
        "duration_seconds": None,
    }
    html = templates.get_template("partials/run_row.html").render(run=run, initial=True)
    assert '<tr id="run-row-7">' in html
    assert 'hx-get="/runs/7/status"' in html
    assert 'hx-trigger="load, every 2s"' in html
    assert 'hx-target="#run-row-7"' in html
    assert 'hx-swap="outerHTML"' in html
    assert "width:40%" in html
    assert "Reconciliation" in html


def test_run_row_completed_stops_polling():
    run = {
        "id": 8,
        "scenario": "baseline_run",
        "status": "completed",
        "current_stage": "Complete",
        "progress_percent": 100,
        "started_at": "2026-10-23 09:00:00",
        "duration_seconds": 12,
    }
    html = templates.get_template("partials/run_row.html").render(run=run)
    assert '<tr id="run-row-8">' in html
    assert "hx-get" not in html
    assert "width:100%" in html
    assert "12s" in html


def test_status_endpoint_returns_row_and_stops_when_completed():
    run_id = _insert_run()
    try:
        running = client.get(f"/runs/{run_id}/status")
        assert running.status_code == 200
        assert f'<tr id="run-row-{run_id}">' in running.text
        assert 'hx-trigger="every 2s"' in running.text
        assert f'hx-target="#run-row-{run_id}"' in running.text
        assert "width:40%" in running.text
        assert "Reconciliation" in running.text

        execute(
            "UPDATE runs SET status='completed', current_stage='Complete', "
            "progress_percent=100, duration_seconds=7 WHERE run_id=%s",
            (run_id,),
        )
        done = client.get(f"/runs/{run_id}/status")
        assert done.status_code == 200
        assert f'<tr id="run-row-{run_id}">' in done.text
        assert "hx-get" not in done.text
        assert "width:100%" in done.text
        assert "7s" in done.text
    finally:
        _delete_run(run_id)


def test_post_validation_returns_single_row(monkeypatch):
    run_id = _insert_run(status="running", stage="Queued", pct=0)
    monkeypatch.setattr(
        pages, "_trigger_validation", lambda request, scenario: (run_id, None)
    )
    try:
        response = client.post("/runs", data={"scenario": "baseline_run"})
        assert response.status_code == 200
        text = response.text.strip()
        assert text.startswith("<tr ")
        assert text.endswith("</tr>")
        assert text.count("<tr") == 1
        assert f'id="run-row-{run_id}"' in text
        assert f'hx-get="/runs/{run_id}/status"' in text
        assert 'hx-trigger="load, every 2s"' in text
        assert f'hx-target="#run-row-{run_id}"' in text
        assert "Queued" in text
        assert "banner" not in text
    finally:
        _delete_run(run_id)


def test_status_endpoint_unknown_run_still_returns_row():
    response = client.get("/runs/999999999/status")
    assert response.status_code == 200
    assert '<tr id="run-row-999999999">' in response.text
    assert "unknown" in response.text
