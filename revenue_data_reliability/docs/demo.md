# Demo

## URLs

| Environment | URL |
|---|---|
| Production | https://revenue-platform-prod.onrender.com |
| Staging | https://revenue-platform-staging.onrender.com |
| Health | https://revenue-platform-prod.onrender.com/health |

Production starts empty. A human loads a seed — that is intentional.

## Datasets

| Seed | Label | Story |
|---|---|---|
| 101 | Seed 1 (Neutral) | Flat performance; misses target |
| 102 | Seed 2 (Bullish) | Outperforms target |
| 103 | Seed 3 (Bearish) | Declining performance |

All are 12-month, pre-generated, reproducible datasets. The platform does not
generate data inside FastAPI.

## Walkthrough

| # | Page | Persona | Action | Expected |
|---|---|---|---|---|
| 1 | `/runs` | Analyst | Load Dataset → Seed 1 (Neutral) → Load | Dataset row appears |
| 2 | `/runs` | Analyst | Validate | 11 rules run; progress completes |
| 3 | `/runs/{id}` | Analyst | Review results | Rule table + publication block |
| 4 | `/exceptions` | Analyst / Manager | Review open issues | Period, severity, thread |
| 5 | `/runs/{id}` | Manager | Approve Go-Live | Publication created; dashboard unlocks |
| 6 | `/` | Any | Open Dashboard | Target Attainment, charts, threads |

If go-live is blocked, clear the open issues on `/exceptions` first.

## What to look for

| Page | Signal |
|---|---|
| `/` | Target Attainment, revenue/billings/target, variance bridges, concentration |
| `/runs` | Run status, rule results, publication state |
| `/exceptions` | Open queue, monthly reconciliation detail |
| `/audit` | Agent actions, approvals, publications (app-wide) |
| `/observability` | Traces, span tree, linked logs, metrics (app-wide) |

## Personas

| Persona | Try |
|---|---|
| Analyst | Load a dataset, validate, post in a thread |
| Manager | Approve go-live, dismiss or execute remediation |
| Director | Reset demo data, receive critical escalations |
