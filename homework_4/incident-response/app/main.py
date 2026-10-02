"""Incident responder: Grafana webhook receiver.

On POST /alerts it saves an incident bundle (alert labels/annotations,
affected endpoint, recent Loki logs, Tempo traces) plus a ready-to-run
headless coding-assistant prompt. Nothing is executed automatically:
starting the assistant means running the `opencode run` command from the
generated PROMPT_<id>.md. Alerts labelled test=true are log-only.
"""

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("incident.response")

INCIDENTS_DIR = Path(os.getenv("INCIDENTS_DIR", "incidents"))
LOKI_URL = os.getenv("LOKI_URL", "http://loki:3100").rstrip("/")
TEMPO_URL = os.getenv("TEMPO_URL", "http://tempo:3200").rstrip("/")
FETCH_TIMEOUT = float(os.getenv("EVIDENCE_TIMEOUT_SECONDS", "5"))

DEFAULT_ENDPOINT = "GET /api/orders/{order_id}"
DASHBOARD_PATH = "/d/order-tracker-requests/order-tracker-requests-and-errors"


class Alert(BaseModel):
    status: str = "firing"
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    startsAt: str = ""
    endsAt: str = ""
    fingerprint: str = ""
    values: dict[str, float] = Field(default_factory=dict)


class Webhook(BaseModel):
    receiver: str = ""
    status: str = ""
    alerts: list[Alert] = Field(default_factory=list)
    groupLabels: dict[str, str] = Field(default_factory=dict)


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-")
    return slug[:60] or "alert"


def _extract_endpoint(alert: Alert) -> str:
    if alert.annotations.get("endpoint"):
        return alert.annotations["endpoint"]
    text = " ".join(
        alert.annotations.get(k, "") for k in ("description", "summary")
    )
    match = re.search(r"\b(GET|POST|PATCH|PUT|DELETE)\s+(/\S*)", text)
    if match:
        return f"{match.group(1)} {match.group(2).rstrip('.,;')}"
    return DEFAULT_ENDPOINT


def _fetch_loki_logs() -> dict[str, Any]:
    """Recent order-tracker logs. Best-effort: never raises."""
    try:
        resp = httpx.get(
            f"{LOKI_URL}/loki/api/v1/query_range",
            params={"query": '{service_name="order-tracker"}', "limit": "20"},
            timeout=FETCH_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {}).get("result", [])
        return {
            "streams": len(data),
            "samples": [
                {
                    "stream": {k: v for k, v in s.get("stream", {}).items()
                               if k in ("severity_text", "detected_level", "service_name")},
                    "values": [v[1][:500] for v in s.get("values", [])[-3:]],
                }
                for s in data[:5]
            ],
        }
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def _fetch_tempo_traces() -> dict[str, Any]:
    """Recent traces. Best-effort: never raises."""
    import time

    try:
        end = int(time.time())
        resp = httpx.get(
            f"{TEMPO_URL}/api/search",
            params={"start": end - 900, "end": end, "limit": "5"},
            timeout=FETCH_TIMEOUT,
        )
        resp.raise_for_status()
        traces = resp.json().get("traces", [])
        return {
            "traces": len(traces),
            "recent": [
                {
                    "traceID": t.get("traceID"),
                    "rootServiceName": t.get("rootServiceName"),
                    "rootTraceName": t.get("rootTraceName"),
                }
                for t in traces
            ],
        }
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}"}


def _prompt_text(incident_id: str, alert: Alert, endpoint: str) -> str:
    dashboard = alert.annotations.get(
        "dashboard", f"http://127.0.0.1:3000{DASHBOARD_PATH}")
    return f"""# Incident {incident_id} — headless assistant prompt

Alert `{alert.labels.get("alertname", "unknown")}` is {alert.status}.
Affected endpoint: {endpoint}
Summary: {alert.annotations.get("summary", "")}
Dashboard: {dashboard}

Evidence: see `incidents/{incident_id}.json` in this folder
(logs, traces, labels, annotations).

Do NOT fix the intentional `estimated_delivery` bug in
order-tracker unless the homework says so. Diagnose first:
confirm the 5xx in Prometheus (`otel_http_server_request_count_total`),
correlate the Loki error stream via trace_id, open the Tempo trace.

Simulated headless launch (run by a human — nothing auto-executes):

```
opencode run "Investigate incident {incident_id} using incidents/{incident_id}.json and report root cause"
```
"""


def handle_alert(alert: Alert) -> dict[str, Any]:
    """Persist bundle + prompt for one real alert. Never raises."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    name = _slug(alert.labels.get("alertname", "alert"))
    incident_id = f"{stamp}-{name}-{_slug(alert.fingerprint[-8:])}"
    endpoint = _extract_endpoint(alert)

    bundle: dict[str, Any] = {
        "incident_id": incident_id,
        "received_at": datetime.now(timezone.utc).isoformat(),
        "status": alert.status,
        "endpoint": endpoint,
        "labels": alert.labels,
        "annotations": alert.annotations,
        "startsAt": alert.startsAt,
        "fingerprint": alert.fingerprint,
        "values": alert.values,
        "dashboard": alert.annotations.get(
            "dashboard", f"http://127.0.0.1:3000{DASHBOARD_PATH}"),
        "evidence": {
            "loki": _fetch_loki_logs(),
            "tempo": _fetch_tempo_traces(),
        },
    }
    INCIDENTS_DIR.mkdir(parents=True, exist_ok=True)
    bundle_path = INCIDENTS_DIR / f"{incident_id}.json"
    bundle_path.write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    prompt_path = INCIDENTS_DIR / f"PROMPT_{incident_id}.md"
    prompt_path.write_text(
        _prompt_text(incident_id, alert, endpoint), encoding="utf-8")

    logger.info(
        "incident %s saved (alert=%s endpoint=%s bundle=%s)",
        incident_id, alert.labels.get("alertname"), endpoint, bundle_path,
    )
    logger.info(
        "headless assistant launch simulated for %s — run the command in %s",
        incident_id, prompt_path,
    )
    return {"incident_id": incident_id, "endpoint": endpoint}


app = FastAPI(title="Incident Response")


@app.get("/healthz")
def health():
    return {"status": "ok"}


@app.get("/incidents")
def list_incidents():
    if not INCIDENTS_DIR.is_dir():
        return []
    return sorted(p.stem for p in INCIDENTS_DIR.glob("*.json"))


@app.get("/incidents/{incident_id}")
def get_incident(incident_id: str):
    path = INCIDENTS_DIR / f"{_slug(incident_id)}.json"
    if not path.is_file():
        from fastapi import HTTPException
        raise HTTPException(404, "Incident not found")
    return FileResponse(path, media_type="application/json")


@app.post("/alerts")
def receive_alerts(webhook: Webhook):
    received = len(webhook.alerts)
    incidents: list[dict[str, Any]] = []
    skipped_tests = 0
    for alert in webhook.alerts:
        if alert.labels.get("test") == "true":
            skipped_tests += 1
            logger.info(
                "test alert %s acknowledged (log-only, no bundle)",
                alert.labels.get("alertname"),
            )
            continue
        try:
            incidents.append(handle_alert(alert))
        except Exception as exc:  # never fail the webhook with 5xx
            logger.exception("failed to handle alert: %s", exc)
            incidents.append({"incident_id": None, "error": str(exc)})
    return {
        "received": received,
        "incidents": incidents,
        "skipped_tests": skipped_tests,
    }
