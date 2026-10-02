# Homework 4 — Observability & Incident Response

Two services that form a closed observability loop for the AI Dev Tools
Zoomcamp homework:

| Service | Dir | Role |
| --- | --- | --- |
| Order Tracker | `order-tracker/` | FastAPI + SQLite order API with OTel traces/metrics/logs |
| Incident Response | `incident-response/` | Grafana webhook receiver + on-call agent launcher |

## The loop (all verified live)

1. **App** (`:8000`) emits telemetry via OTLP to the Collector → Prometheus,
   Loki, Tempo; Grafana dashboard shows request counts and errors.
2. **Alert** (`Order Tracker 5xx errors`, 5m window, 30s eval) fires on any
   5xx and POSTs to the responder (`:8001`) via a provisioned webhook.
3. **Responder** saves an incident bundle (endpoint, Loki logs, Tempo
   traces) and auto-launches a headless `opencode` agent (free Zen model),
   which diagnoses, minimally fixes, tests, and redeploys.
4. The loop already closed one real incident: the month-end
   `estimated_delivery` 500 on `express-1002`, fixed with a regression test
   (see `order-tracker/AGENTS.md` §8). Humans review `RESULT_<id>.md` and
   `git diff` — nobody hand-fixes, nothing auto-commits.

## Run it

```bash
cd order-tracker && docker compose up --build -d --wait
cd ../incident-response && docker compose up --build -d --wait
```

Tests: `uv run --frozen pytest -q` in each folder. Details live in each
service's `README.md` and `order-tracker/AGENTS.md`.
