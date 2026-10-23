"""Tests for observability route rendering."""


def test_observability_route_renders():
    from fastapi.testclient import TestClient

    from backend.main import app

    client = TestClient(app)
    r = client.get("/observability")
    assert r.status_code == 200
    # Page should mention traces or spans.
    assert "trace" in r.text.lower() or "span" in r.text.lower()
