import pytest
from fastapi.testclient import TestClient

from app import main


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "INCIDENTS_DIR", tmp_path / "incidents")
    # Loki/Tempo unreachable in tests -> evidence fetchers return {"error": ...}
    monkeypatch.setattr(main, "LOKI_URL", "http://127.0.0.1:9")
    monkeypatch.setattr(main, "TEMPO_URL", "http://127.0.0.1:9")
    with TestClient(main.app) as test_client:
        yield test_client


def firing_payload():
    return {
        "receiver": "webhook",
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "OrderTracker5xx", "severity": "critical"},
                "annotations": {
                    "summary": "5xx responses detected",
                    "description": "Spike on GET /api/orders/{order_id} in the last 5m",
                },
                "startsAt": "2026-10-02T14:00:00Z",
                "fingerprint": "abc123",
            }
        ],
    }


def test_health(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_firing_alert_saves_bundle_and_prompt(client):
    resp = client.post("/alerts", json=firing_payload())
    assert resp.status_code == 200
    body = resp.json()
    assert body["received"] == 1
    assert body["skipped_tests"] == 0
    incident_id = body["incidents"][0]["incident_id"]
    assert body["incidents"][0]["endpoint"] == "GET /api/orders/{order_id}"

    bundle = client.get(f"/incidents/{incident_id}").json()
    assert bundle["endpoint"] == "GET /api/orders/{order_id}"
    assert "loki" in bundle["evidence"] and "tempo" in bundle["evidence"]
    assert client.get("/incidents").json() == [incident_id]


def test_test_label_is_log_only(client, tmp_path):
    payload = firing_payload()
    payload["alerts"][0]["labels"] = {
        "alertname": "ResponderTest",
        "test": "true",
    }
    resp = client.post("/alerts", json=payload)
    assert resp.status_code == 200
    assert resp.json() == {"received": 1, "incidents": [], "skipped_tests": 1}
    assert client.get("/incidents").json() == []


def test_malformed_body_is_422(client):
    assert client.post("/alerts", json={"alerts": "nope"}).status_code == 422
    assert client.get("/incidents/does-not-exist").status_code == 404
