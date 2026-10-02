# AGENTS.md — Order Tracker (HW4 Observability)

Root context for `homework_4/order-tracker/`. Read this first before editing anything in this folder.

## 1. What this is

AI Dev Tools Zoomcamp 2026, Homework 4: observability and incident response exercise.

A small order-tracking service: web page + API + tests + Docker Compose setup.
The main user flow is creating an order and checking its status. Three sample
orders are seeded on first startup. The course exercise is detecting and
handling an incident, not scaling the database.

## 2. Current progress (Q2 done + observability stack)

Commit `c51abe8` — `saving progress after question 2`:

> coding agent added OTel for order lookups, bug was detected and intentionally
> left intact for testing (homework objective)

Plus Collector stack (this session, in working tree — see `git status`):

- OTel traces / metrics / logs for order lookups implemented in
  `app/telemetry.py` + `app/main.py`, dual-export: console (for
  `docker compose logs app`) + OTLP/HTTP to Collector
  (`OTEL_EXPORTER_OTLP_ENDPOINT`, default `http://otel-collector:4318`).
- `observability/otel-collector.yaml` (contrib 0.156.0): OTLP receiver,
  pipelines traces→Tempo (otlp_grpc), metrics→Prometheus exporter `:8889`
  (namespace `otel`), logs→Loki via OTLP/HTTP (`otlp_http`).
- `compose.yaml` services: `app`, `otel-collector` (4317/4318),
  `prometheus` (9090), `loki` (3100), `tempo` (3200), `grafana` (3000,
  admin/admin, file-provisioned datasources + dashboard).
- Dashboard `observability/grafana/dashboards/orders.json`:
  `Order Tracker - Requests and Errors` on
  `otel_http_server_request_count_total` (by status, 5xx, error rate,
  404-vs-500). Verified live: counts for 200/404/500, Loki streams with
  trace correlation incl. `day is out of range for month` stacktrace,
  Tempo traces with root `order.lookup`, Grafana auto-loads the dashboard.
- Follow-up verification (same session): `curl.exe` against the running
  stack returns `200` for `standard-1001`, `404` for unknown ids
  (e.g. `standard-1002` does not exist), `500` for `express-1002`.
  (Note: Windows PowerShell `curl` is an `Invoke-WebRequest` alias —
  always use `curl.exe`.)
- Alert done (this session, in working tree): Grafana-managed
  `Order Tracker 5xx errors` (`uid: order-tracker-5xx`,
  `observability/grafana/alerting/alert-5xx.yaml`), file-provisioned,
  30s eval / 1m `for`, `noDataState: OK`. Verified live:
  Normal (empty window) → Firing (after `express-1002` traffic).
- Responder done (this session, in working tree): `homework_4/incident-response/`
  (FastAPI, own compose on shared `order-tracker_default` network, `:8001`).
  `POST /alerts` saves bundle (`incidents/<id>.json`: labels, endpoint,
  Loki logs, Tempo traces) + headless prompt (`PROMPT_<id>.md`, run by hand —
  nothing auto-executes). `test=true` alerts are log-only. Grafana webhook
  contact point (`notify-webhook.yaml`, `severity=critical` → responder)
  verified: ResponderTest → 200 skipped; drill firing → bundle with
  10 Loki streams + 2 Tempo traces.

## 3. Intentional bug — DO NOT FIX

`order_detail()` in `app/main.py:64-70`:

```python
placed_at.replace(day=placed_at.day + 2)
```

- Raises for `express` orders placed near end-of-month (day + 2 overflows).
- Seeded order `express-1002` uses `previous_month_end`, so
  `GET /api/orders/express-1002` reliably returns 500.
- `app/telemetry.py:1-5` docstring explicitly says to leave it in place so the
  500 is observable via telemetry.
- Use it to verify spans / metrics / logs and later alerts. Do not patch it
  unless the homework prompt explicitly says to.

## 4. Architecture + file map

```
order-tracker/
├── AGENTS.md            # this file (agent recovery context)
├── README.md            # run instructions, API table, observability URLs
├── compose.yaml         # app + otel-collector + prometheus + loki + tempo + grafana
├── Dockerfile           # python:3.12-slim + uv, uvicorn on :8000
├── pyproject.toml       # fastapi, uvicorn, opentelemetry-{api,sdk,instrumentation-fastapi,exporter-otlp-proto-http}
├── observability/
│   ├── otel-collector.yaml
│   ├── prometheus.yaml  # scrapes otel-collector:8889
│   ├── loki.yaml
│   ├── tempo.yaml
│   └── grafana/
│       ├── datasources.yaml       # Prometheus pinned to uid: prometheus (alert queries need it)
│       ├── dashboard-provider.yaml
│       ├── alerting/alert-5xx.yaml  # Grafana-managed 5xx rule (30s/1m, noData OK)
│       ├── alerting/notify-webhook.yaml  # webhook contact point + critical routing
│       └── dashboards/orders.json
├── app/
│   ├── __init__.py
│   ├── main.py          # lifespan, routes, middleware, order.lookup span
│   └── telemetry.py     # all OTel setup, constants, lazy getters
├── static/index.html    # create order + check status UI
└── tests/test_api.py    # health + seed, create/update, 404
```

- SQLite at `ORDER_DB_PATH` (default `data/orders.db`, `/data/orders.db` in
  container). One app container at a time. Volume survives recreation.
- Routes: `GET /`, `GET /healthz`, `GET /api/orders`, `POST /api/orders`,
  `GET /api/orders/{id}`, `PATCH /api/orders/{id}`.

## 5. Telemetry contract (authoritative for this folder)

`app/telemetry.py`:

- `SERVICE_NAME = "order-tracker"`, `ORDER_LOOKUP_ROUTE = "/api/orders/{order_id}"`.
- `setup_telemetry(app)` is idempotent (guards on `app.state.otel_initialized`).
- `Resource(service.name=order-tracker)`, dual export:
  traces via `BatchSpanProcessor(ConsoleSpanExporter)` + `OTLPSpanExporter`,
  metrics via console `PeriodicExportingMetricReader` (5s) + OTLP reader (15s),
  logs via `BatchLogRecordProcessor(ConsoleLogExporter)` + `OTLPLogExporter`.
  OTLP endpoint from `OTEL_EXPORTER_OTLP_ENDPOINT`
  (default `http://otel-collector:4318`).
- When `PYTEST_CURRENT_TEST` is set, exporters are skipped (no console spam).
- `FastAPIInstrumentor().instrument_app(app)` for auto server spans.
- Lazy getters for tests: `get_tracer()`, `get_request_instruments()`,
  `get_order_logger()` (logger name `order.lookup`).

`app/main.py`:

- `lifespan` calls `setup_telemetry(app)` then `init_db()`.
- `order_lookup_metrics` middleware records only for
  `GET /api/orders/{id}` (prefix + length check): histogram
  `http.server.request.duration` (ms) + counter `http.server.request.count`
  with attrs `http.route`, `http.response.status_code`, `http.method=GET`.
- `GET /api/orders/{order_id}` opens span `order.lookup` with
  `order.id`, then sets `order.found`, `http.response.status_code`,
  `order.priority`, `order.status`. 404 and 500 set
  `Status(StatusCode.ERROR, ...)` and log via `order.lookup` logger
  (`info` on found/not_found, `exception` on error).

## 6. Commands

```bash
# run (needs Docker with Compose)
docker compose up --build -d --wait
# open http://127.0.0.1:8000, API at /api/orders, health at /healthz

# port override
ORDER_TRACKER_PORT=18080 docker compose up --build -d --wait

# tail telemetry (spans/metrics/logs go to stdout)
docker compose logs -f app

# tests (needs Python 3.11+ and uv)
uv run --frozen pytest -q

# stop (add -v only to also delete order data)
docker compose down
```

Trigger paths (seeded ids: `standard-1001`, `express-1002`, `standard-1003`):

- OK (200): `GET /api/orders/standard-1001`
- Bug (500): `GET /api/orders/express-1002`
- Not found (404): `GET /api/orders/missing` (any unknown id, e.g. `standard-1002` does not exist)

Windows PowerShell: `curl` is an `Invoke-WebRequest` alias that swallows
`-i` and prompts for `Uri:` — always use `curl.exe` and prefer
`127.0.0.1` over `localhost` (compose binds `127.0.0.1`).

Observability UIs: Grafana `http://127.0.0.1:3000` (admin/admin),
Prometheus `http://127.0.0.1:9090`. Port overrides: `GRAFANA_PORT`,
`PROMETHEUS_PORT`, `LOKI_PORT`, `TEMPO_PORT`.

Gotchas learned this session:

- `otel/opentelemetry-collector-contrib:0.129.0` does not resolve;
  `0.156.0` verified. The `loki` exporter is absent from contrib
  0.156.0 — logs go via `otlp_http` exporter to Loki's OTLP endpoint
  (`http://loki:3100/otlp`). Use canonical component names (`otlp_http`,
  `otlp_grpc`); the `otlp`/`otlphttp` aliases log deprecation warnings.
- `observability/otel-collector.yaml` is bind-mounted, so editing it does
  NOT recreate the container — apply with
  `docker compose up -d --force-recreate --wait otel-collector`.
- Prometheus metric name for the counter is
  `otel_http_server_request_count_total` (`otel` namespace prefix + dots
  → underscores); status label is `http_response_status_code`.

## 7. Constraints for next agent

- Dual export stays: console + OTLP. No vendor backend, no new
  OTel packages without asking. Image pins live in `compose.yaml`
  (collector-contrib 0.156.0, prometheus v3.3.1, loki 3.4.2, tempo 2.7.1,
  grafana 11.6.5); bump only if `docker pull` fails.
- Keep `setup_telemetry` idempotent and test-safe (`PYTEST_CURRENT_TEST`).
- Keep middleware lookup-only. Do not instrument list/create/patch paths
  unless the homework asks.
- Do not fix the `estimated_delivery` bug (§3). Do not add auth, multi-user,
  scaling, or Postgres — out of scope for this exercise.
- Python: `ruff` + strict typing where practical, `logging` never `print`
  (OTel logging goes through `order.lookup` logger).

## 8. Next steps (responder done — verify/polish)

Alert + responder are built and verified (Normal → Firing → Normal;
webhook → bundle + prompt). Remaining polish if the homework asks:

Alert-rule gotchas learned:

- The `threshold` expression type does not parse in Grafana 11.6 file
  provisioning (`no variable specified to reference`). Use
  query A (PromQL range) → B (`reduce`, `last`, on A) → C (`math`, `$B > 0`),
  condition C. A bare `math` on range data fails with
  `only reduced data can be alerted on` — the reduce step is mandatory.
- Like all provisioning, new alert files need a Grafana
  `--force-recreate` (bind-mounts don't trigger reloads).
- Rule state API (no UI needed):
  `GET /api/prometheus/grafana/api/v1/rules` → `state`/`health`/`alerts`;
  rule detail: `GET /api/v1/provisioning/alert-rules/order-tracker-5xx`.

## 9. Definition of done (for telemetry changes)

1. `uv run --frozen pytest -q` passes.
2. `docker compose up --build -d --wait` healthy, `/healthz` returns ok.
3. `GET /api/orders/express-1002` → 500 with `order.lookup` error span +
   exception log in `docker compose logs app`, log stream in Loki, trace in
   Tempo, 500 bump in Prometheus `otel_http_server_request_count_total` and
   Grafana dashboard.
4. `GET /api/orders/<valid-id>` → 200 with `order.found=true` span + info log.
5. No new dependency added without asking.
