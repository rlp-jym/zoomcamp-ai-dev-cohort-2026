# Order Tracker

A small order tracking app for the AI Dev Tools Zoomcamp observability homework. It includes a web page, API, tests, and a Docker Compose setup. You add telemetry, alerts, and an incident responder in Homework 4.

The main user flow is creating an order and checking its status. Three sample orders are created on first startup.

## Run it

You need Docker with Compose. To run the tests, you also need Python 3.11+ and `uv`.

```bash
docker compose up --build -d --wait
```

Open <http://127.0.0.1:8000>. The API is at `/api/orders`, and the health check is at `/healthz`. Data is stored in a Docker volume and survives container recreation.

If port 8000 is occupied, set `ORDER_TRACKER_PORT`, for example:

```bash
ORDER_TRACKER_PORT=18080 docker compose up --build -d --wait
```

Run tests with `uv run --frozen pytest -q`. Stop the app with `docker compose down`. Add `-v` only if you also want to delete the order data.

## Observability

`docker compose up` also starts an OpenTelemetry Collector plus Prometheus,
Loki, Tempo, and Grafana. The app sends traces, metrics, and logs via OTLP/HTTP
to the Collector (`OTEL_EXPORTER_OTLP_ENDPOINT`, default
`http://otel-collector:4318`) while keeping console output for `docker compose
logs app`. All configs live in `observability/` and the Grafana dashboard is
file-provisioned from `observability/grafana/dashboards/orders.json`.

| UI | URL |
| --- | --- |
| Grafana (admin/admin) | <http://127.0.0.1:3000> |
| Prometheus | <http://127.0.0.1:9090> |

Port overrides: `GRAFANA_PORT`, `PROMETHEUS_PORT`, `LOKI_PORT`, `TEMPO_PORT`
(same pattern as `ORDER_TRACKER_PORT`).

The dashboard `Order Tracker - Requests and Errors` shows request counts by
status, 5xx errors, error rate, and 404-vs-500 split, backed by
`otel_http_server_request_count_total`. To generate an error, open
`GET /api/orders/express-1002` (intentional 500, see `AGENTS.md`).

## Alert

Grafana ships a file-provisioned alert, `Order Tracker 5xx errors`
(`observability/grafana/alerting/alert-5xx.yaml`), on any 5xx in a 5m
window (evaluated every 30s, fires after 1m pending). Empty windows resolve
to Normal (`noDataState: OK`), so quiet periods never page. The alert
annotation names the endpoint, the 5m window, and links the dashboard.
Check its state under Alerting → Alert rules in Grafana. Firing
`severity=critical` alerts are delivered to the incident responder
(`../incident-response`, `POST /alerts` on port 8001), which saves an
incident bundle (endpoint, logs, traces) plus a headless-assistant prompt.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/` | Web page |
| GET | `/healthz` | Database health check |
| GET | `/api/orders` | List orders |
| POST | `/api/orders` | Create an order |
| GET | `/api/orders/{id}` | Check an order |
| PATCH | `/api/orders/{id}` | Change an order status |

The app uses SQLite to keep setup small. Run one app container at a time. The course exercise is about detecting and handling an incident, not scaling the database.
