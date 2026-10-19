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
    c.post("/persona", data={"persona_id": "manager"})
    r = c.get("/")
    assert "FP&amp;A Manager" in r.text or "Manager" in r.text


def test_htmx_post_message():
    c = TestClient(app)
    r = c.post("/threads/analysis/kpi-revenue/messages", data={"content": "smoke msg"})
    assert r.status_code == 200
    assert "smoke msg" in r.text