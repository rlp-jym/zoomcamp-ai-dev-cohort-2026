# Incident Response

Receives Grafana alert webhooks for the HW4 observability exercise and saves
everything needed to understand the problem: alert labels/annotations, the
affected endpoint, recent Loki logs, and Tempo traces.

On a real alert it also launches the on-call coding assistant automatically
(`opencode run` headless, in a background thread) with a constrained brief:
diagnose, minimal fix under `order-tracker/app` + `order-tracker/tests`,
`pytest` gate, rebuild/restart the app, write `RESULT_<id>.md`. It never
commits. Single-flight: one agent run at a time. Alerts labelled `test=true`
are acknowledged log-only (no bundle, no launch).

## Model credentials (free Zen tier by default)

The agent authenticates with your **existing host OpenCode login** — no paid
key needed. A trimmed copy holding only the `opencode` entry
(`.zen-auth.json`, gitignored — refresh it if your Zen login rotates) is
mounted read-only into the container, and the model is pinned via
`OPENCODE_MODEL` (default `opencode/muse-spark-1.3-contributor-free`;
any `opencode/*-free` id works).

A paid-key fallback remains: copy `.env.example` to `.env` (gitignored,
loaded via compose `env_file`) and fill in one provider key. Without any
credentials the agent run fails gracefully (`RESULT_` records it) and the
bundle is still saved. Free-tier runs only spend Zen quota — zero cost.

## Run it

The order-tracker stack must be up first (it owns the shared
`order-tracker_default` network):

```bash
cd ../order-tracker && docker compose up -d --wait
cd ../incident-response && docker compose up --build -d --wait
```

Open <http://127.0.0.1:8001/incidents> for saved bundles.
Override the port with `INCIDENT_RESPONSE_PORT` (same pattern as
`ORDER_TRACKER_PORT`).

Run tests with `uv run --frozen pytest -q`.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/alerts` | Grafana webhook receiver (also used for manual drills) |
| GET | `/incidents` | List saved incident bundle ids |
| GET | `/incidents/{id}` | Fetch one bundle (labels, endpoint, Loki/Tempo evidence) |
| GET | `/healthz` | Health check |

## Test it

Test alert (log-only, expect `skipped_tests: 1`, no bundle):

```powershell
curl.exe --globoff -s -X POST http://127.0.0.1:8001/alerts `
  -H "Content-Type: application/json" `
  --data "@<path-to-payload>.json"
```

with payload:

```json
{"alerts": [{"status": "firing", "labels": {"alertname": "ResponderTest", "test": "true"}, "annotations": {"summary": "Test notification; no incident to fix"}}]}
```

Real drill: generate 500s (`curl.exe http://127.0.0.1:8000/api/orders/express-1002`),
POST a firing payload without the `test` label, then check `/incidents` —
expect `<id>.json` (endpoint, Loki streams, Tempo traces), `PROMPT_<id>.md`
(the brief the agent received), and — once the agent finishes —
`RESULT_<id>.md` (root cause, files changed, test output).

PowerShell notes: use `curl.exe` (bare `curl` is an `Invoke-WebRequest`
alias) and `--globoff` with `--data "@file"` for JSON payloads.
