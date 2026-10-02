# Incident Response

Receives Grafana alert webhooks for the HW4 observability exercise and saves
everything needed to understand the problem: alert labels/annotations, the
affected endpoint, recent Loki logs, and Tempo traces.

On a real alert it also writes a ready-to-run headless coding-assistant
prompt (`PROMPT_<id>.md`). Nothing executes automatically — starting the
assistant means running the `opencode run` command from that file by hand.
Alerts labelled `test=true` are acknowledged log-only (no bundle, no prompt).

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
expect `<id>.json` (endpoint, Loki streams, Tempo traces) plus
`PROMPT_<id>.md` in the `incidents/` volume.

PowerShell notes: use `curl.exe` (bare `curl` is an `Invoke-WebRequest`
alias) and `--globoff` with `--data "@file"` for JSON payloads.
