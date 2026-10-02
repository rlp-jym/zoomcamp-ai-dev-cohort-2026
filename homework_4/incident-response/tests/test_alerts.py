import subprocess
import time

import pytest
from fastapi.testclient import TestClient

from app import main


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "INCIDENTS_DIR", tmp_path / "incidents")
    # Loki/Tempo unreachable in tests -> evidence fetchers return {"error": ...}
    monkeypatch.setattr(main, "LOKI_URL", "http://127.0.0.1:9")
    monkeypatch.setattr(main, "TEMPO_URL", "http://127.0.0.1:9")
    monkeypatch.setattr(main, "WORK_DIR", tmp_path / "work")
    monkeypatch.setattr(main, "AGENT_ENABLED", True)
    calls = []
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: calls.append((a, k)) or subprocess.CompletedProcess(
            a[0], 0, stdout="agent-ok", stderr=""),
    )
    with TestClient(main.app) as test_client:
        test_client.calls = calls
        yield test_client


def _wait_for(path, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if path.is_file():
            return True
        time.sleep(0.1)
    return False


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


def test_firing_alert_saves_bundle_and_prompt(client, tmp_path):
    resp = client.post("/alerts", json=firing_payload())
    assert resp.status_code == 200
    body = resp.json()
    assert body["received"] == 1
    assert body["skipped_tests"] == 0
    assert body["incidents"][0]["agent_launched"] is True
    incident_id = body["incidents"][0]["incident_id"]
    assert body["incidents"][0]["endpoint"] == "GET /api/orders/{order_id}"

    bundle = client.get(f"/incidents/{incident_id}").json()
    assert bundle["endpoint"] == "GET /api/orders/{order_id}"
    assert "loki" in bundle["evidence"] and "tempo" in bundle["evidence"]
    assert client.get("/incidents").json() == [incident_id]

    # stubbed agent ran once with the opencode headless command ...
    assert len(client.calls) == 1
    assert client.calls[0][0][0][:2] == ["opencode", "run"]
    # ... and wrote its result file, releasing the lock.
    incidents = tmp_path / "incidents"
    assert _wait_for(incidents / f"RESULT_{incident_id}.md")
    assert not (incidents / ".agent.lock").exists()

    # ... and left an agent-readable evidence copy inside the work tree.
    agent_dir = tmp_path / "work" / ".agent" / incident_id
    assert (agent_dir / "bundle.json").is_file()
    assert (agent_dir / "PROMPT.md").is_file()


def test_agent_disabled_launches_nothing(client, monkeypatch):
    monkeypatch.setattr(main, "AGENT_ENABLED", False)
    body = client.post("/alerts", json=firing_payload()).json()
    assert body["incidents"][0]["agent_launched"] is False
    assert client.calls == []


def test_single_flight_skips_second_launch(client, tmp_path):
    (tmp_path / "incidents").mkdir()
    (tmp_path / "incidents" / ".agent.lock").write_text("123")
    body = client.post("/alerts", json=firing_payload()).json()
    assert body["incidents"][0]["agent_launched"] is False
    assert client.calls == []


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
