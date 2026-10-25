# Revenue Data Reliability Platform

Synthetic B2B-distribution revenue data is ingested, validated, reconciled to
the General Ledger, and published only after a human approves it. A team of
agents triages data issues in anchored discussion threads; a Controller verifies
the published state on a schedule.

## Live demo

| Environment | URL | Notes |
|---|---|---|
| Production | https://revenue-platform-prod.onrender.com | `main`; empty until a dataset is loaded |
| Staging | https://revenue-platform-staging.onrender.com | `staging`; pre-loaded demo data |
| Health | https://revenue-platform-prod.onrender.com/health | `{"status":"ok"}` |

## Start here

| # | Page | Persona | Action | Expected |
|---|---|---|---|---|
| 1 | `/runs` | Analyst | Load Dataset → **Seed 1 (Neutral)** → Load | Dataset appears |
| 2 | `/runs` | Analyst | **Validate** | 11 rules run |
| 3 | `/runs/{id}` | Analyst | Review results | Rule table + publication block |
| 4 | `/exceptions` | Analyst / Manager | Review open issues | Queue with period and severity |
| 5 | `/runs/{id}` | Manager | **Approve Go-Live** | Publication created |
| 6 | `/` | Any | Open Dashboard | Target Attainment, charts, threads |

Seeds: **Seed 1 (Neutral)**, **Seed 2 (Bullish)**, **Seed 3 (Bearish)**. All are
12-month, pre-generated datasets. If go-live is blocked, clear the open issues
on `/exceptions` first.

## What works

| Area | Implementation |
|---|---|
| Validation | 11 DuckDB rules over Parquet on R2 |
| Reconciliation | Billings vs GL at `(period, account_id, item_category)` |
| Exceptions | One per affected month per failed rule; latest period stays open |
| Agents | Orchestrator, DQ, DE, Financial Impact, Controller |
| Publication | Manager-gated go-live; published pointer + quarantine overlay |
| Observability | Traces, metrics, structured logs in Postgres; in-app viewer |
| Dashboard | Target Attainment plus revenue, growth, category, customer, variance, concentration views |

## Operating model

| Principle | Implementation |
|---|---|
| Timeliness over precision | Validation fires on tolerable variance, not zero variance |
| Human-gated publication | Manager approves go-live and remediation; agents propose |
| Controller as counterweight | Freshness SLA + continuous verification; critical alerts escalate |
| Narrow autonomy | `STALE_PUBLISHED` triggers revalidation, not republication |
| Immutable raw data | DE's only executable action is quarantine; Parquet is never altered |

See [docs/operating-model.md](docs/operating-model.md).

## Course core vs domain extension

| Layer | Covers |
|---|---|
| Course core | Full-stack app, persistent Postgres, anchored discussion threads, agent team, observability, deployment |
| Domain extension | 11 validation rules, billings-vs-GL reconciliation, publication gates, persona responsibilities, Controller verification |

The discussion thread is the core interaction; the pipeline exists to give it
something worth discussing.

## Architecture

```mermaid
flowchart LR
  U[Browser / HTMX] --> F[FastAPI routes]
  F --> S[Services]
  S --> P[(Postgres)]
  S --> D[DuckDB]
  D --> R[(R2 Parquet)]
  S --> A[Agent team]
  A --> P
  F --> O[OTEL exporter]
  O --> P
```

| Agent | Writes | Executes |
|---|---|---|
| Orchestrator | Run start/finish | Pipeline |
| DQ | Validation summary | 11 rules |
| DE | Remediation proposal | Quarantine after approval |
| Financial Impact | Impact narrative | None |
| Controller | Alerts, triage, escalation | Revalidation on stale publication |

See [docs/architecture.md](docs/architecture.md).

## Repository map

| Path | Contents |
|---|---|
| `backend/` | FastAPI app, routes, services, agents, skills, DB |
| `frontend/` | Jinja templates, HTMX, CSS |
| `data/` | Synthetic generator + fixtures (own AGENTS.md) |
| `infra/` | Dockerfile, Render blueprint, provider docs |
| `observability/` | OTEL setup + Postgres exporter |
| `tests/` | Unit + integration tests |
| `docs/` | Spec, tasks, definitions, operating model, demo, deployment |
| `src/` | `uv_build` package root |

## Run locally

```bash
cp .env.example .env          # Windows: Copy-Item .env.example .env
docker compose -f infra/docker-compose.yml up --build
```

App: http://localhost:8000 · Health: `/health` · Postgres: `localhost:5432`.

Without Docker (with Postgres running):

```bash
uv sync --extra dev
uvicorn backend.main:app --reload
```

## Tests

```bash
export TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rlp_test  # macOS/Linux
$env:TEST_DATABASE_URL="postgresql://postgres:postgres@localhost:5432/rlp_test"  # PowerShell
uv run pytest -n auto
```

CI runs lint plus the full suite against a Postgres service container.

## Roles

| Role | Type | Responsibility |
|---|---|---|
| Analyst | Human | Loads datasets, triggers validation, authors analyses |
| Manager | Human | Approves go-live and remediation |
| Director | Human | Receives critical escalations; can reset demo data |
| Orchestrator / DQ / DE / FA / Controller | Agents | Pipeline, validation, remediation proposal, financial impact, verification |

## Docs

| Doc | Purpose |
|---|---|
| [docs/spec.md](docs/spec.md) | Locked architecture and scope |
| [docs/tasks.md](docs/tasks.md) | Public task tracker |
| [docs/definitions.md](docs/definitions.md) | Metric definitions and materiality |
| [docs/operating-model.md](docs/operating-model.md) | Timeliness/accuracy trade-off |
| [docs/demo.md](docs/demo.md) | End-user walkthrough |
| [docs/architecture.md](docs/architecture.md) | System flow and agents |
| [docs/deployment.md](docs/deployment.md) | Environments, CI/CD, rollback |
| [docs/challenges.md](docs/challenges.md) | Engineering challenges |
| [docs/backlog.md](docs/backlog.md) | Verified behavior checklist |

## CI/CD

| Workflow | Trigger | Action |
|---|---|---|
| `test.yml` | PRs and pushes | Lint + tests (Postgres service) |
| `deploy-staging.yml` | Push to `staging` | Tests, then Render deploy |
| `deploy-prod.yml` | Push to `main` | Manual approval, then Render deploy |
| `scenario-generate.yml` | Manual | Generate dataset, upload to R2, register via webhook |

See [docs/deployment.md](docs/deployment.md).

## Known limits

| Limit | Mitigation |
|---|---|
| Render 512 MB | 12-month window, DuckDB 200 MB / 1 thread, local Parquet cache |
| Free Postgres | State-only schema; 30-day telemetry retention |
| No auth | Persona selector for demo; documented non-goal |
| LLM optional | Template fallback when `GROQ_API_KEY` is empty |
