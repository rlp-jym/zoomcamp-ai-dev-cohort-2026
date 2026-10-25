# Revenue Data Reliability Platform

Synthetic B2B-distribution revenue data is ingested, validated, reconciled to
the General Ledger, and published only after a human approves it. A team of
agents triages data issues in anchored discussion threads; a Controller verifies
the published state on a schedule.

## Live Demo

| Environment | URL | Notes |
|---|---|---|
| Production | https://revenue-platform-prod.onrender.com | `main`; empty until a dataset is loaded |
| Staging | https://revenue-platform-staging.onrender.com | `staging`; pre-loaded demo data |
| Health | https://revenue-platform-prod.onrender.com/health | `{"status":"ok"}` |

## Start Here

| # | Page (URL) | Persona | Action | Expected |
|---|---|---|---|---|
| 1 | Validation (`/runs`) | FP&A Analyst | Load Dataset → **Seed 1 (Neutral)** → Load | Dataset appears |
| 2 | Validation (`/runs`) | FP&A Analyst | **Validate** | 12 rules run |
| 3 | Validation (`/runs/{id}`) | FP&A Analyst | Review results | Rule table + publication block |
| 4 | Data Issues (`/exceptions`) | FP&A Analyst / FP&A Manager | Review open issues | Queue with period and severity |
| 5 | Validation (`/runs/{id}`) | FP&A Manager | **Approve Go-Live** | Publication created |
| 6 | Dashboard (`/`) | Any | Open Dashboard | Target Attainment, charts, threads |

### Pre-Generated Datasets

| Seed | Label | Story | S3 Prefix |
|---|---|---|---|
| 101 | Seed 1 (Neutral) | Flat performance; misses target | `scenarios/seed_101/` |
| 102 | Seed 2 (Bullish) | Outperforms target | `scenarios/seed_102/` |
| 103 | Seed 3 (Bearish) | Declining performance | `scenarios/seed_103/` |

All three are 12-month, pre-generated datasets. The platform does not generate
data inside FastAPI. If go-live is blocked, clear the open issues on Data Issues
(`/exceptions`) first.

## What Works

| Area | Implementation |
|---|---|
| Validation | 12 DuckDB rules over Parquet on R2 |
| Reconciliation | Billings vs GL at `(period, account_id, item_category)` |
| Data Issues | One per affected month per failed rule; latest period stays open |
| Agents | Pipeline Orchestrator, Data Quality, Data Engineer, Financial Impact Agent, Controller |
| Publication | FP&A Manager-gated go-live; published pointer + quarantine overlay |
| Observability | Traces, metrics, structured logs in Postgres; in-app viewer |
| Dashboard | Target Attainment plus revenue, growth, category, customer, variance, concentration views |

## Operating Model

| Principle | Implementation |
|---|---|
| Timeliness over precision | Validation fires on tolerable variance, not zero variance |
| Human-gated publication | FP&A Manager approves go-live and remediation; agents propose |
| Controller as counterweight | Freshness SLA + continuous verification; critical alerts escalate |
| Narrow autonomy | `STALE_PUBLISHED` triggers revalidation, not republication |
| Immutable raw data | Data Engineer's only executable action is quarantine; Parquet is never altered |

See [docs/operating-model.md](docs/operating-model.md).

## Course Core and Domain Extension

| Layer | Covers |
|---|---|
| Course core | Full-stack app, persistent Postgres, anchored discussion threads, agent team, observability, deployment |
| Domain extension | 12 validation rules, billings-vs-GL reconciliation, publication gates, persona responsibilities, Controller verification |

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
| Pipeline Orchestrator | Run start/finish | Pipeline |
| Data Quality | Validation summary | 12 rules |
| Data Engineer | Remediation proposal | Quarantine after approval |
| Financial Impact Agent | Impact narrative | None |
| Controller | Alerts, triage, escalation | Revalidation on stale publication |

See [docs/architecture.md](docs/architecture.md).

## Repository Map

| Path | Contents |
|---|---|
| `backend/` | FastAPI app, routes, services, agents, skills, DB |
| `frontend/` | Jinja templates, HTMX, CSS |
| `data/` | Offline generator + fixtures (historical; not used at runtime) |
| `infra/` | Dockerfile, Render blueprint, provider docs |
| `observability/` | OTEL setup + Postgres exporter |
| `tests/` | Unit + integration tests |
| `docs/` | Spec, tasks, definitions, operating model, demo, deployment |
| `src/` | `uv_build` package root |

## Run Locally

```bash
cp .env.example .env          # optional; Windows: Copy-Item .env.example .env
docker compose up --build
```

App: http://localhost:8000 · Health: `/health` · Postgres: `localhost:5432`.
`.env` supplies R2 and Groq credentials; without it the app starts with local
Postgres and empty storage.

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

| Role (ID) | Type | Responsibility |
|---|---|---|
| FP&A Analyst (`analyst`) | Human | Loads datasets, triggers validation, authors analyses |
| FP&A Manager (`manager`) | Human | Approves go-live and remediation |
| Director of FP&A (`director`) | Human | Receives critical escalations; can reset demo data |
| Pipeline Orchestrator (`orchestrator`) | Agent | Runs the pipeline; posts start/finish |
| Data Quality (`dq`) | Agent | Runs the 12 rules; posts the validation summary |
| Data Engineer (`de`) | Agent | Proposes remediation; executes quarantine after approval |
| Financial Impact Agent (`fa`) | Agent | Quantifies the financial impact of each issue |
| Controller (`controller`) | Agent | Verifies published state; opens alerts; escalates |

## Docs

| Doc | Purpose |
|---|---|
| [docs/spec.md](docs/spec.md) | Locked architecture and scope |
| [docs/tasks.md](docs/tasks.md) | Public task tracker; acceptance criteria per section |
| [docs/definitions.md](docs/definitions.md) | Metric definitions and materiality |
| [docs/operating-model.md](docs/operating-model.md) | Timeliness/accuracy trade-off |
| [docs/demo.md](docs/demo.md) | End-user walkthrough |
| [docs/architecture.md](docs/architecture.md) | System flow and agents |
| [docs/deployment.md](docs/deployment.md) | Environments, CI/CD, rollback |
| [docs/challenges.md](docs/challenges.md) | Engineering challenges and workarounds |
| [docs/traceability.md](docs/traceability.md) | Rubric and build evidence map |

Task sections carry "Done when" acceptance criteria. The checkbox history and the
commit history are the evidence that the agent team worked through them.

## CI/CD

| Workflow | Trigger | Action |
|---|---|---|
| `test.yml` | PRs and pushes | Lint + tests (Postgres service) |
| `deploy-staging.yml` | Push to `staging` | Tests, then Render deploy |
| `deploy-prod.yml` | Push to `main` | Manual approval, then Render deploy |
| `scenario-generate.yml` | Manual | Disabled; offline generator retained for reproducibility |

See [docs/deployment.md](docs/deployment.md).

## Known Limits

| Limit | Mitigation |
|---|---|
| Render 512 MB | 12-month window, DuckDB 200 MB / 1 thread, local Parquet cache |
| Free Postgres | State-only schema; 30-day telemetry retention |
| No auth | Persona selector for demo; documented non-goal |
| LLM optional | Template fallback when `GROQ_API_KEY` is empty |
