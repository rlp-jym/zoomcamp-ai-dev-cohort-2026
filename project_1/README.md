# Revenue Data Reliability Platform

## Problem Statement
A platform that ingests synthetic B2B-distribution revenue data, validates it,
reconciles billings to GL, and surfaces exceptions via a team of AI agents and
human discussion.

## Current Status
Batch 4 complete. All 11 validation rules execute against every run, the
billings-vs-GL reconciliation runs at the `(period, account_id, item_category)`
grain, exceptions are raised for every failed rule (grouped by month) and every
material reconciliation gap, and the DQ agent posts a validation summary on the
run thread. The UI is wired to real Postgres/DuckDB data on every route.

Implemented in this phase:
- 11 DuckDB validation rules over Parquet on Filebase (`backend/db/seed.py`).
- Generic rule execution + result storage (`validations` table).
- Rule-to-exception grouping by `period` (one exception per affected month).
- DQ agent summary (template fallback, no LLM) on the run thread.
- Reconciliation job writing `reconciliations` and opening material-gap exceptions.
- `/runs/{id}` renders all 11 validation results; `/exceptions/{id}` drills into
  monthly reconciliation rows for reconciliation exceptions.

Still stubbed / later batches: dashboard KPI wiring, DE / FA / Controller agents,
publication + quarantine, alerting, OTEL export, APScheduler, real LLM calls.

## Data Reset & Baseline Fixture

A persistent `baseline_run` fixture is seeded on boot. It includes a registered scenario, a completed and published baseline run, a matching publication, and a minimal run thread. This keeps the dashboard populated immediately after cold starts and resets.

Reset modes:
- Preserve baseline (recommended): truncates non-baseline application data while keeping personas, rules, and the baseline fixture intact.
- Full reset: removes all data including the baseline fixture (set `SEED_BASELINE_FIXTURE=0` and truncate everything).

Local helper scripts: `run_app.bat` (starts app and opens browser after health check), `stop_app.bat` (stops app on port 8000).

## How to Run (Local)
`uvicorn backend.main:app --reload`

Single command (app + Postgres via Docker): `docker compose up` — see `infra/`.

## Expected Behavior
- Analyst selects a persona in the header and can "Run Pipeline" on a scenario.
- The run thread shows Orchestrator start/finish, the DQ validation summary, and a
  reconciliation line.
- `/exceptions` lists validation and reconciliation exceptions with their period.
- `/runs/{id}` shows pass/fail/count for all 11 rules.
- `/exceptions/{id}` on a reconciliation exception shows the monthly rows behind it.
- Debug routes `/debug/db`, `/debug/storage`, `/debug/query` remain available.

## UI Build Note (Two Phases)
Templates were built as stubs in Batch 1 and wired to real data in Batch 4
(§19). Template edits after this point are expected as wiring lands.

## Tests
Single command: `pytest` (unit + integration, exits 0). See `tests/`.

## Documentation Links
- Architecture & Scope: `SPEC.md`
- Metric Definitions & KPI Rationale: `definitions.md`
- Build Roadmap: `TASKS.md`
- Agent Skill Definitions: `backend/skills/`
- Data Generator: `data/README.md` and `data/AGENTS.md`
