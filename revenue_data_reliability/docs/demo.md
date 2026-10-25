# Demo

## URLs

| Environment | URL |
|---|---|
| Production | https://revenue-platform-prod.onrender.com |
| Staging | https://revenue-platform-staging.onrender.com |
| Health | https://revenue-platform-prod.onrender.com/health |

Production starts empty. A human loads a seed — that is intentional.

## Datasets

| Seed | Label | Story | S3 Prefix |
|---|---|---|---|
| 101 | Seed 1 (Neutral) | Flat performance; misses target | `scenarios/seed_101/` |
| 102 | Seed 2 (Bullish) | Outperforms target | `scenarios/seed_102/` |
| 103 | Seed 3 (Bearish) | Declining performance | `scenarios/seed_103/` |

All three are 12-month, pre-generated, reproducible datasets. The platform does
not generate data inside FastAPI. The generator is kept for reproducibility; the
app does not invoke it at runtime.

## Walkthrough

| # | Page (URL) | Persona | Action | Expected |
|---|---|---|---|---|
| 1 | Validation (`/runs`) | FP&A Analyst | Load Dataset → Seed 1 (Neutral) → Load | Dataset row appears |
| 2 | Validation (`/runs`) | FP&A Analyst | Validate | 11 rules run; progress completes |
| 3 | Validation (`/runs/{id}`) | FP&A Analyst | Review results | Rule table + publication block |
| 4 | Data Issues (`/exceptions`) | FP&A Analyst / FP&A Manager | Review open issues | Period, severity, thread |
| 5 | Validation (`/runs/{id}`) | FP&A Manager | Approve Go-Live | Publication created; dashboard unlocks |
| 6 | Dashboard (`/`) | Any | Open Dashboard | Target Attainment, charts, threads |

If go-live is blocked, clear the open issues on Data Issues (`/exceptions`) first.

## What to Look For

| Page (URL) | Signal |
|---|---|
| Dashboard (`/`) | Target Attainment, revenue/billings/target, variance bridges, concentration |
| Validation (`/runs`) | Run status, rule results, publication state |
| Data Issues (`/exceptions`) | Open queue, monthly reconciliation detail |
| Audit (`/audit`) | Agent actions, approvals, publications (app-wide) |
| Observability (`/observability`) | Traces, span tree, linked logs, metrics (app-wide) |

## Personas

| Persona (ID) | Try |
|---|---|
| FP&A Analyst (`analyst`) | Load a dataset, validate, post in a thread |
| FP&A Manager (`manager`) | Approve go-live, dismiss or execute remediation |
| Director of FP&A (`director`) | Reset demo data, receive critical escalations |

Agents are also selectable in the header for inspection; the human personas
drive the demo.
