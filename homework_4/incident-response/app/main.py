"""Incident responder: Grafana webhook receiver and on-call agent launcher.

On POST /alerts it saves an incident bundle (alert labels/annotations,
affected endpoint, recent Loki logs, Tempo traces) plus the agent brief
(PROMPT_<id>.md), then launches a headless coding assistant (`opencode run`)
in a background thread. The agent owns diagnosis and the minimal fix;
alerts labelled test=true are log-only and never launch anything.
"""

import json
import logging
import os
import re
import subprocess
import threading
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
WORK_DIR = Path(os.getenv("WORK_DIR", "/work/order-tracker"))
WORK_ROOT = Path(os.getenv("WORK_ROOT", "/work"))
AGENT_EVIDENCE_SUBDIR = ".agent"
AGENT_TIMEOUT = int(os.getenv("AGENT_TIMEOUT_SECONDS", "600"))
AGENT_ENABLED = os.getenv("AGENT_ENABLED", "true").lower() == "true"
LOCK_NAME = ".agent.lock"

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
    return f"""# Incident {incident_id} — on-call agent brief (executed headless)

You are the first on-call engineer. Your working directory is the repo root
(`{WORK_ROOT}`); everything you need is inside it. Alert
`{alert.labels.get("alertname", "unknown")}` is {alert.status}.
Affected endpoint: {endpoint}
Summary: {alert.annotations.get("summary", "")}
Dashboard: {dashboard}

Evidence (read these first, all inside your working directory):
- `./order-tracker/{AGENT_EVIDENCE_SUBDIR}/{incident_id}/bundle.json`
  (alert labels/annotations, recent Loki logs, Tempo traces)
- this brief: `./order-tracker/{AGENT_EVIDENCE_SUBDIR}/{incident_id}/PROMPT.md`

## Mission

Diagnose the 5xx and fix it with the MINIMAL code change. You own this fix.

## Rules

1. Read the bundle first. Confirm the failing endpoint and the error.
2. Edit ONLY under `./order-tracker/app` and `./order-tracker/tests`.
   Touch nothing else (no observability configs, no credentials, no `.agent`
   evidence copies, no other homework).
3. Keep the change minimal — fix the defect, do not refactor or add features.
4. Gate: run the service test suite in `{WORK_DIR}` and make it pass
   (`UV_PROJECT_ENVIRONMENT=/tmp/ot-venv uv run --frozen pytest -q` —
   the venv MUST live in /tmp, never in the bind-mounted work tree).
   Add a regression test for this exact failure if one does not exist.
5. Redeploy: `docker compose -f {WORK_DIR}/compose.yaml up -d --build app`
   and verify the endpoint no longer 5xx. NOTE — networking from THIS
   container: host-published ports (`http://127.0.0.1:8000`) are NOT
   reachable here; talk to the app as `http://app:8000` (compose DNS),
   e.g. `curl -s http://app:8000/api/orders/express-1002` must not
   return 500. ALSO NOTE — bind mounts: this daemon resolves `-v`
   host-paths on ITS OWN filesystem, so `up` may recreate sibling
   containers (collector/loki/tempo) with broken config mounts. Build
   contexts stream client-side and are safe. After redeploying, check
   `docker compose -f {WORK_DIR}/compose.yaml ps`; if siblings are
   restarting, SAY SO in your report and do NOT touch their configs —
   a human re-runs `up` from the host to heal mounts.
6. NEVER commit or push. Leave the diff in the working tree for human review.
7. NEVER print secrets. If no model credentials are available, stop and say
   so in your final message, changing nothing.

## Report

Do NOT write any RESULT file yourself. Put your final report as your LAST
message: root cause, files changed, test results, verification output.
The launcher saves it as `RESULT_{incident_id}.md`.
"""


def _try_acquire_lock() -> bool:
    """Single-flight: only one agent run at a time. Returns True if acquired."""
    INCIDENTS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(INCIDENTS_DIR / LOCK_NAME, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        return False


def _release_lock() -> None:
    try:
        (INCIDENTS_DIR / LOCK_NAME).unlink()
    except FileNotFoundError:
        pass


def run_agent(incident_id: str, brief: str) -> dict[str, Any]:
    """Execute `opencode run` headless on the brief. Blocking. Never raises."""
    result_path = INCIDENTS_DIR / f"RESULT_{incident_id}.md"
    try:
        proc = subprocess.run(
            ["opencode", "run", brief],
            cwd=str(WORK_ROOT),
            capture_output=True,
            text=True,
            timeout=AGENT_TIMEOUT,
        )
        outcome = {
            "incident_id": incident_id,
            "returncode": proc.returncode,
            "stdout_tail": proc.stdout[-4000:],
            "stderr_tail": proc.stderr[-2000:],
        }
    except FileNotFoundError:
        outcome = {"incident_id": incident_id,
                   "error": "opencode binary not found in container"}
    except subprocess.TimeoutExpired:
        outcome = {"incident_id": incident_id,
                   "error": f"agent timed out after {AGENT_TIMEOUT}s"}
    except Exception as exc:
        outcome = {"incident_id": incident_id, "error": str(exc)}
    try:
        lines = [f"# Result {incident_id}", ""]
        for key, value in outcome.items():
            lines.append(f"## {key}")
            lines.append("")
            lines.append(f"```\n{value}\n```")
            lines.append("")
        result_path.write_text("\n".join(lines), encoding="utf-8")
    except Exception as exc:
        logger.exception("failed to write result file: %s", exc)
    logger.info("agent run finished for %s: %s", incident_id, result_path)
    return outcome


def _launch_in_background(incident_id: str, brief: str) -> bool:
    """Start the on-call agent unless disabled or one is already running."""
    if not AGENT_ENABLED:
        logger.info("agent launch disabled (AGENT_ENABLED=false) for %s",
                    incident_id)
        return False
    if not _try_acquire_lock():
        logger.info("agent already running — skipping launch for %s",
                    incident_id)
        return False

    def _run() -> None:
        try:
            run_agent(incident_id, brief)
        finally:
            _release_lock()

    threading.Thread(target=_run, daemon=True,
                     name=f"agent-{incident_id}").start()
    logger.info("on-call agent launched for %s (workdir=%s)",
                incident_id, WORK_DIR)
    return True


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
    brief = _prompt_text(incident_id, alert, endpoint)
    prompt_path.write_text(brief, encoding="utf-8")
    # Agent-visible evidence copy inside its project root (/work), so the
    # sandbox allows reads. Canonical bundle stays in INCIDENTS_DIR.
    agent_dir = WORK_DIR / AGENT_EVIDENCE_SUBDIR / incident_id
    try:
        agent_dir.mkdir(parents=True, exist_ok=True)
        (agent_dir / "bundle.json").write_text(
            json.dumps(bundle, indent=2), encoding="utf-8")
        (agent_dir / "PROMPT.md").write_text(brief, encoding="utf-8")
    except Exception as exc:
        logger.exception("failed to write agent evidence copy: %s", exc)

    logger.info(
        "incident %s saved (alert=%s endpoint=%s bundle=%s)",
        incident_id, alert.labels.get("alertname"), endpoint, bundle_path,
    )
    launched = _launch_in_background(incident_id, brief)
    return {"incident_id": incident_id, "endpoint": endpoint,
            "agent_launched": launched}


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
