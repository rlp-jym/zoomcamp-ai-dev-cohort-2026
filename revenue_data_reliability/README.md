# Revenue Data Reliability Platform

## Problem Statement
A platform that ingests synthetic B2B-distribution revenue data, validates it,
reconciles billings to the General Ledger, and surfaces data issues via a team
of AI agents and human discussion threads.

## Current Status
Production-shaped v1. All 11 validation rules execute against every run, the
billings-vs-General-Ledger reconciliation runs at the `(period, account_id,
item_category)` grain, and exceptions are raised for every failed rule (grouped
by month) and every material reconciliation gap. The DQ/DE/Financial Impact
Agent/Controller agents post to run and exception threads (template fallback
when no LLM key is set).

The UI is wired to real Postgres/DuckDB data on every route. Generated
datasets are first-class: each has its own validation runs, issues, and
published pointer, and the default view prefers the most recently published
dataset.

Implemented highlights:
- 11 DuckDB validation rules over Parquet on R2.
- Generic rule execution + result storage (`validations` table).
- Per-category reconciliation: GL is allocated from each category's own
  billings with a small per-category bias, split across accounts; billings are
  expanded across account rows by each row's GL share. Variance % is
  `(billings - gl) / gl`; status pass/fail by tolerance.
- Rule-to-exception grouping by `period` (one exception per affected month).
  Only the latest data period stays `open`; earlier periods are inserted
  `resolved` so `/exceptions` stays a pending work queue.
- Agent team: Orchestrator (pipeline), DQ (validation summary), DE
  (remediation proposals), Financial Impact Agent (financial impact),
  Controller (continuous verification of published state, 6 checks, alerting).
- Publication flow: Manager approves go-live; published pointer + quarantine
  overlay; Controller verifies published state on a schedule.
- Observability: OpenTelemetry spans/logs/metrics exported to Postgres with
  an in-app viewer and a retention job.
- Dashboard: historical actuals + FP&A assessment. Target Attainment card
  (General Ledger revenue as % of target, with the latest month in the title),
  then three charts
  (Revenue/Billings/Target, Variances by Category, Month-over-Month Growth)
  plus a Billings-by-Customer-Segment bar chart. Each chart carries its own
  discussion thread. Forward-looking projections are not on the dashboard —
  they are authored under Scenarios.
- Scenarios: repurposed as a forward-looking sensitivity workspace bound to the
  latest published run (title, outcome/projection, assessment, thread).
- Synthetic data window 2022-01 to 2026-12 (60 months), reproducible per seed.
- Terminology in the UI: Runs → Validation, Exceptions → Data Issues,
  Budget → Target. Nav order: Dashboard, Scenarios, Validation, Data Issues,
  Audit, Observability.

Still open / later work: CI/CD, Dockerfile, infra docs, unit/integration tests,
scenario data snapshot capture, remaining `dimension_drift` config wiring,
`VAL_SEGMENT_DRIFT` rule, and per-segment order volume weighting.

## Data Reset & Baseline Cleanup

The pre-loaded `baseline_run` dataset is retired. Generated datasets carry their
own runs and publication pointers, and boot no longer recreates the baseline
once any dataset exists.

One-time cleanup (dry run by default):

```text
python -m backend.db.cleanup
python -m backend.db.cleanup --apply
```

The script deletes the `baseline_run` dataset row plus its runs, exceptions,
validation results, reconciliations, quarantines, publications, discussions,
approvals, alerts, and telemetry. It **never deletes S3/Filebase Parquet
files**.

Set `SEED_BASELINE_FIXTURE=1` only when you explicitly want the legacy fixture
seeded (tests force it in their isolated database).

## Demo Setup

### Why pre-ingested datasets?

In a production environment, this platform ingests live ERP/CRM data. To assist the reviewer and avoid overloading the 512MB Render container with a 31-million-row generation job, we have pre-generated three distinct datasets (Seeds 101, 102, 103) and uploaded them to Filebase S3. The "Load Dataset" feature allows the reviewer to instantly load these datasets into the environment to test the validation pipeline, remediation loop, and dashboard.

### Pre-generated Datasets

The Load Dataset action never runs the data generator inside FastAPI (Render's
512 MB container cannot hold a generation run). Datasets are generated offline
with `data/generate.py` and uploaded once:

| Seed | Dataset | S3 prefix |
|---|---|---|
| 101 | `generated_seed101_y5` | `scenarios/seed_101/` |
| 102 | `generated_seed102_y5` | `scenarios/seed_102/` |
| 103 | `generated_seed103_y5` | `scenarios/seed_103/` |

`POST /api/generate-scenario` only registers the dataset row and points
`datasets.s3_prefix` at the matching folder. Unknown seeds return HTTP 400 with
the available seed list. Dashboards and validation read the dataset's own
`datasets.s3_prefix`; there is no `baseline_run` fallback.

Local helper scripts: `run_app.bat` (starts app and opens browser after health
check), `stop_app.bat` (stops app on port 8000).

## How to Run (Local)
`uvicorn backend.main:app --reload` (or `.venv/Scripts/python.exe -m uvicorn
backend.main:app --host 127.0.0.1 --port 8000`)

Single command (app + Postgres via Docker): `docker compose -f infra/docker-compose.yml up --build` — see `infra/README.md`.

## Expected Behavior
- Analyst selects a persona in the header; navigation persists via cookie.
- Dashboard shows Target Attainment and the four charts, each with its own
  thread; posting a message updates via HTMX.
- `/scenarios` lists sensitivity analyses bound to the latest published run;
  Analysts can create new ones (title, outcome/projection, assessment).
- `/validation` (formerly Runs) lists runs; `/validation/{id}` shows all 11
  validation results, publication block, and approve/reject actions
  (Manager-gated).
- `/data-issues` (formerly Exceptions) lists validation and reconciliation
  exceptions with their period; defaults to `open` with `Resolved` and `All`
  views and a trend chart; `/data-issues/{id}` drills into monthly
  reconciliation rows.
- `/audit` shows agent_actions, approvals, publications (filterable by
  `trace_id`).
- `/observability` shows traces, span trees, and linked logs.
- Pipeline runs are triggered via script only (no in-app Run Pipeline button).

## Problem Statement

B2B distribution revenue data arrives from multiple systems (billing, GL, budget).
Each run must be validated, reconciled, and reviewed before publication. Data
issues need to be surfaced, discussed, and resolved by a team of AI agents and
human reviewers.

## System Functionality

- Ingest synthetic revenue data (Parquet on R2) for a run.
- Execute 11 DuckDB validation rules over the run's tables.
- Reconcile billings to the General Ledger at `(period, account_id, item_category)`.
- Raise exceptions for failed rules and material reconciliation gaps.
- Run an agent team (Orchestrator, DQ, DE, Financial Impact Agent, Controller)
  that posts to discussion threads with template fallback when no LLM key is set.
- Manager approves publication; published pointer + quarantine overlay.
- Observability: OpenTelemetry spans/logs/metrics exported to Postgres with an
  in-app viewer.

## Expected Behavior

See the "Expected Behavior" section above.

## Role Definitions

| Role | Type | Responsibility |
|---|---|---|
| Analyst | Human | Generates datasets, initiates validation, authors sensitivity scenarios. |
| Manager | Human | Governs the remediation loop: approves or rejects with a reason. |
| DE (Data Engineer) | Agent | Proposes and executes data quarantines/remediation. |
| Financial Impact Agent | Agent | Translates data issues into financial narratives and impact estimates. |
| Controller | Agent | Continuous post-publication verification; opens alerts and escalates. |

### Governance Loop (Human-in-the-loop)

The AI proposes; the human decides. The DE agent posts a remediation proposal
and the Manager either executes the fix or dismisses it as a false positive.
The Financial Impact Agent attaches a financial narrative to each issue so the
human decision is grounded in monetary impact.

**Governance constraint:** to maintain data immutability and audit trails, the
Data Engineer (DE) Agent's only executable action is Quarantine (excluding rows
from dashboard calculations without altering the raw Parquet files).
Consequently, the Manager's available decisions are limited to
"Execute Fix" or "Dismiss (False Positive)".

## Demo Flow

1. Start the app: `docker compose -f infra/docker-compose.yml up --build`.
2. Open http://localhost:8000 - the dashboard opens on the most recently
   published dataset.
3. Switch persona in the header; navigation persists via cookie.
4. Review `/data-issues`, `/validation`, `/audit`, `/observability`.
5. Create a Scenario under `/scenarios`.
6. Run the pipeline via script: `python run_generator.py` (or the scenario
   generator workflow).

## Two-Phase UI Build

The UI was built in two phases: a skeleton with stub data (§1b) followed by
wiring to real Postgres/DuckDB data (§19). Template edits between phases are
expected.

## OpenTelemetry Deviation

Traces, spans, and logs are stored in Postgres and viewed in-app via
`/observability`. No external Grafana/Jaeger backend is used (SPEC.md §20
non-goal).

## Tests

Tests require a dedicated database and must never point at the live app DB:

```bash
export TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rlp_test
uv run pytest -n auto
```

Unit and integration tests use a Postgres service container (CI) or the local
Docker Postgres. R2 and Groq calls are mocked.

## Documentation Links

- Architecture & Scope: `SPEC.md`
- Engineering Challenges: `CHALLENGES.md`
- Metric Definitions: `definitions.md`
- Build Roadmap: `TASKS.md`
- Agent Skill Definitions: `backend/skills/`
- Data Generator: `data/README.md`, `data/AGENTS.md`
- Infra: `infra/README.md`, `infra/NEON.md`, `infra/R2.md`, `infra/SECRETS.md`
- Branching: `_docs/branching-strategy.md`
