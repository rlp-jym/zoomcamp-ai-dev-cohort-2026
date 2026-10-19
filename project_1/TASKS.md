# TASKS.md — Revenue Data Reliability Platform

Project path: repository root (`project_1/`). Tracks the application build
against `SPEC.md` (locked). Check boxes as work completes. Do not build
anything listed in `SPEC.md §20 (Explicit non-goals)`.

> This file is the public task tracker, hosted in the project's GitHub
> repository. Commit history is the evidence that agents used this
> tracker: each commit message references a task section (e.g.,
> `§9: implement VAL_FK_ITEM_EXISTS`).
>
> Project-level acceptance criteria live in `SPEC.md §18`.
> Section-level "Done when" criteria are listed at the end of §2, §5, §8,
> §9, §13, §18, §19, and §23.

## 0. Prerequisites before build (`SPEC.md §19`)
> §1, §1b, §2, §4, and §6 can proceed in parallel with the unchecked prerequisites. §5 and §7 onwards depend on `definitions.md` and the regenerated `baseline_run` (16 tables, seed=9). §19 depends on §1b being complete.
- [x] Generator updated to emit `budget` table (reference-only) — see `data/TASKS.md` §6b.
- [x] `baseline_run` generated with seed=9 and registered name `baseline_run` (16 tables).
- [ ] `data/AGENTS.md`, `data/TASKS.md`, `data/SOURCES.md` updated and consistent with generator.
- [ ] `definitions.md` written (revenue, billings, DSO, fill rate, materiality).
- [ ] Root `README.md` updated with project overview + link to `SPEC.md`.

## 1. Repository scaffolding
- [x] Create directory structure from `SPEC.md §4` (`frontend/templates`, `frontend/static`, `backend/routes`, `backend/services`, `backend/teams`, `backend/skills`, `backend/db`, `infra`, `observability`).
- [x] Add `backend/__init__.py` and package layout (or flat modules) per locked layout.
- [x] Add `.env.example` listing `DATABASE_URL`, `R2_*`, `GROQ_API_KEY`, `GH_TOKEN`, `WEBHOOK_TOKEN`.
- [x] Add backend dependency manifest (FastAPI, Jinja2, HTMX assets, DuckDB, psycopg3, APScheduler, opentelemetry-sdk, boto3, groq client) — update root `pyproject.toml` or add `backend/pyproject.toml`.
- [x] Configure lint/format (ruff) and pytest.
- [x] Add `backend/main.py` application entry point.

## 1b. UI skeleton (stub data, no backend wiring)
> Build all templates and routes with hardcoded context dicts so every page
> is renderable and reviewable before any DB, DuckDB, or agent wiring. Do
> not call the database, R2, or agents in this section. Templates are
> expected to change once wired in §19.
- [x] Base layout template with persona selector header (stub persona list)
- [x] Reusable thread partial (ordered messages, persona badges, agent
  styling) usable for run, exception, and analysis anchors
- [x] `/` dashboard template with hardcoded KPI cards + inline analysis
  thread partial
- [x] `/exceptions` list template with hardcoded rows
- [x] `/exceptions/{id}` detail + thread template with hardcoded data
- [x] `/runs` list template with hardcoded rows
- [x] `/runs/{id}` detail + thread template with hardcoded data
- [x] `/scenarios` list template + New Scenario button (non-functional)
- [x] `/audit` list template with hardcoded rows
- [x] `/observability` trace list + span tree template with hardcoded data
- [x] Mount all routes returning stub context (no DB calls)
- [x] Wire HTMX partial response for at least one interaction (post
  message) using an in-memory stub
- [x] Extension 1: Add dashboard trend/variance charts (Chart.js, CDN, hardcoded data)
- [x] Extension 2: Add segment and KPI-trend charts plus KPI selection rationale doc

## 2. Database schema and seed data
- [x] Write `backend/db/schema.sql` with idempotent `CREATE TABLE IF NOT EXISTS` for: `personas`, `scenarios`, `runs`, `validations`, `reconciliations`, `exceptions`, `quarantines`, `approvals`, `publications`, `discussions`, `messages`, `alerts`, `agent_actions`, `rules`, `otel_spans`, `otel_logs`, `otel_metrics`.
- [x] Define columns, PKs, FKs, and indexes for discussion threads and trace lookup.
- [x] `discussions` and `messages` tables include `anchor_type` (enum: `run` | `exception` | `analysis`) and `anchor_id` columns with indexes for thread lookup.
- [x] Add `backend/db/seed.py` to seed 8 personas (`analyst`, `manager`, `director`, `orchestrator`, `de`, `dq`, `fa`, `controller`).
- [x] Seed 11 validation rules with `rule_id`, `description`, `severity`, `sql`, `expected_detection_rule`.
- [x] Add DB connection module (psycopg3) with pooling and raw SQL helpers.
- [x] Apply schema on boot; run seeds idempotently.
- [x] Implement backfill: if `scenarios` empty, trigger GitHub Action to generate `baseline_run` (seed=9) and wait for webhook.
**Done when:** All tables exist, 8 personas and 11 rules are seeded, and backfill triggers and completes on an empty DB.

## 3. Storage (R2 + DuckDB)
- [x] Implement R2 client (boto3, S3-compatible) from env.
- [x] Implement DuckDB connection with `httpfs` for reading Parquet from R2.
- [x] Implement scenario bundle path convention `scenarios/<name>/`.
- [x] Implement SHA-256 manifest verification helper.
- [x] Implement published-data query: `DuckDB.read_parquet(R2) − quarantine_filter − non-published runs`. (Consumed by §19 dashboard.)
- [x] Install DuckDB `httpfs` extension at boot; fail loudly if unavailable.
- [ ] Document startup sequence: webhook endpoint must be accepting requests before backfill triggers the GitHub Action.

## 4. Backend foundation
- [x] FastAPI app factory with routers mounted.
- [x] Settings/env loading (pydantic or simple) with validation.
- [x] Persona selection via header dropdown (cookie or header `X-Persona`); no auth.
- [x] Jinja2 templates + static files wiring.
- [x] HTMX-friendly partial responses.
- [x] Global error handling and structured logging.
- [x] Health/readiness endpoint.
- [ ] Mount `POST /api/scenarios/register` webhook route (verify `WEBHOOK_TOKEN`); delegates to §7 handler.

## 5. Observability (OTEL)
- [x] Configure OTEL SDK auto-instrumentation for FastAPI, psycopg3, boto3, DuckDB. (DuckDB has no auto-instrumentor; manual `duckdb.query` spans in `backend/storage/duckdb_client.py`.)
- [x] Implement custom Postgres exporter batching to `otel_spans`, `otel_logs`, `otel_metrics`. (`observability/exporter.py`)
- [x] Propagate `trace_id` into app state and agent actions. (Controller verification uses the OTEL trace id; pipeline/agent actions share the run trace.)
- [x] No PII/credentials in telemetry. (Span attributes carry SQL/statements only; R2 `SET s3_*` connection commands and auth headers are never recorded.)
- [x] Retention job deleting spans/logs older than 30 days (APScheduler). (`observability.telemetry.run_retention`)
- [x] `/observability` route rendering trace list + span tree + linked logs. (`backend/services/observability.py` + `observability.html`)
**Done when:** Any request produces a trace in `/observability` with linked spans and logs, and no span attribute contains PII or credentials.

## 6. Scheduler
- [x] Integrate APScheduler in-process. (`backend/services/scheduler.py`)
- [x] Register Controller verification job (every N minutes).
- [x] Register OTEL retention job.
- [x] Ensure scheduler starts/stops with app lifecycle.

## 7. Scenarios and scenario creation flow
- [x] Scenario CRUD service and repository (raw SQL).
- [x] `/scenarios` route: list + "New Scenario" button (Analyst only).
- [ ] Trigger GitHub Action `workflow_dispatch` using `GH_TOKEN`.
- [x] Webhook endpoint to register scenario from generator (verify `WEBHOOK_TOKEN`).
- [x] Store manifest, file hashes, and scenario metadata.
- [x] Display scenario list with status.

## 8. Runs and pipeline orchestration (scaffold)
> This section builds the run record, Orchestrator skeleton, and routes. The actual rule execution is wired in §9. Do not attempt to run a pipeline with rules until §9 is complete.
- [x] Run CRUD service and repository.
- [x] `/runs` and `/runs/{id}` routes (Analyst, Manager).
- [x] Run detail thread and approve/reject actions.
- [x] Orchestrator service: posts "run started", runs pipeline, posts finish.
- [ ] Pipeline steps: DQ validation → reconciliation → exception creation → DE proposals → FA impact.
- [x] Run status tracking and trace correlation.
**Done when:** Clicking Run Pipeline creates a run row, posts orchestrator messages to the run thread, and returns a run detail page.

## 9. Validation rules (11)
> Depends on §8 scaffold. After implementing rules, wire them into the Orchestrator pipeline built in §8.
- [x] Implement rule loader from `rules` table. (all 11 rules)
- [x] Implement DuckDB SQL execution over Parquet.
- [x] `VAL_FK_ITEM_EXISTS` (orphaned_item_id).
- [x] `VAL_DUPLICATE_INVOICE_LINE` (duplicate_invoice_line).
- [x] `VAL_FK_CUSTOMER_EXISTS` (missing_customer_mapping).
- [x] `VAL_FRESHNESS_GL` (stale_load).
- [x] `VAL_RECON_BILLINGS_GL` (billings_gl_variance).
- [x] `VAL_RESTATEMENT_DETECTED` (restatement).
- [x] `VAL_FX_RATE_EXISTS` (fx_gap).
- [x] `VAL_FK_BACKORDER_ORDER_LINE` (orphaned_backorder).
- [x] `VAL_FK_RETURN_SHIPMENT` (phantom_return).
- [x] `VAL_AR_INVOICE_1TO1` (invariant).
- [x] `VAL_ORDER_LINE_UNIQUE` (invariant).
- [x] Store results in `validations` (`run_id`, `rule_id`, `status`, `summary_count`, `sampled_failures` JSON). (all 11 rules)
- [x] Group failed-rule exceptions by `period` (one exception per affected month).
- [x] DQ posts validation summary to run thread.
**Done when:** All 11 rules execute against a scenario, results are stored in `validations`, and DQ posts a summary to the run thread.

## 10. Reconciliation
- [x] Implement reconciliation at grain `(run_id, period, account_id, item_category)` + top-N customers.
- [x] Billings from `invoice_lines`, GL from `gl_revenue`.
- [x] Variance % = (billings − gl) / gl.
- [x] Status pass/fail by tolerance.
- [x] Materiality threshold from config.
- [x] Store in `reconciliations`.
- [x] Create exceptions for material gaps.

## 11. Exceptions
- [x] Unified `exceptions` table with `type ∈ {validation, reconciliation, quarantine, controller_finding}`.
- [x] Fields: `exception_id`, `run_id`, `type`, `severity`, `period`, `title`, `status`, `trace_id`.
- [x] Status flow: open → in_discussion → remediation_proposed → approved → resolved.
- [x] `/exceptions` queue route.
- [x] `/exceptions/{id}` detail + thread route.
- [x] Exception creation from failed rules and material recon gaps. (VAL_FK_ITEM_EXISTS)

## 12. Discussion model
- [x] `discussions` and `messages` tables with anchor types `run`, `exception`, `analysis`.
- [x] Ordered messages with `persona_id`, `trace_id`, optional `evidence` JSON.
- [x] Single reusable thread UI component (template partial).
- [x] Post message endpoint (human + agent).
- [x] Agent posts visually distinguished (badge, muted background).
- [x] Analysis thread creation from dashboard KPI cards.

## 13. Agent team
- [x] Base agent helpers: logging to `agent_actions`, trace correlation.
- [x] LLM client: Groq primary (`GROQ_API_KEY`), template fallback on missing key/failure.
- [x] Skill loader `load_skill(name) -> str` reading `backend/skills/<name>/SKILL.md`.
- [x] Orchestrator agent: run pipeline; read-only on data.
- [x] DQ agent: execute rules; post validation results.
- [x] DE agent: remediation proposal; bounded writes after approval; playbook steps logged.
- [x] FA agent: financial impact; may open analysis threads.
- [x] Controller agent: verification findings; read-only published state.
- [ ] Approval gates: go-live, remediation, critical escalation.
**Done when:** All 5 agents can be invoked in one pipeline run, each posting to the correct anchor thread and logging exactly one `agent_actions` row.

## 14. Skills (LLM prose layer)
- [x] Create `backend/skills/fa_impact_narrative/SKILL.md`.
- [x] Create `backend/skills/de_remediation_explanation/SKILL.md`.
- [x] Create `backend/skills/dq_validation_summary/SKILL.md`.
- [x] Create `backend/skills/controller_triage_note/SKILL.md`.
- [x] Each SKILL.md: role framing, context fields, output structure/length, hard constraints.
- [x] Template fallbacks equivalent to skill output from same context.

## 15. DE playbook
- [x] Re-run same pipeline for affected month.
- [x] Quarantine N records with reason code.
- [x] Reload FX rates from source (if applicable).
- [x] Post a message on the exception thread tagged `type = proposal` (do not create a new table or a separate note entity).
- [x] Escalate to Manager.
- [x] Each step logged as one `agent_actions` row.

## 16. Alerting (6 types)
- [x] `STALE_PUBLISHED` (high). (`backend/teams/controller.py` → `backend/services/alerts.py`)
- [x] `SOURCE_HASH_MISMATCH` (critical).
- [x] `AUDIT_ROW_MISSING` (high).
- [x] `THREAD_ANCHOR_ORPHANED` (medium).
- [x] `PUBLISHED_RECORD_FAILS_REVALIDATION` (critical).
- [x] `RECON_DRIFT` (critical).
- [x] Dedup by `(alert_type, anchor_id)` in 1-hour window.
- [x] Destinations: `alerts` row + Controller message on anchor thread + dashboard badge.
- [x] Critical alerts escalate to Director via thread message.

## 17. Publication and quarantine
> This section wires together publication, quarantine, and approval flows defined in §8, §11, and §13. Do not duplicate logic here; reference and connect.
- [x] Manager approves go-live in run thread → create `publication` row.
- [x] Set published pointer.
- [x] Quarantine overlay model (`quarantines`).
- [x] Manager approves remediation in exception thread → DE executes → logs `agent_actions`.
- [x] Published data derived at query time with quarantine filter. (Query function ready in `backend/services/publications.py`; dashboard KPI wiring lands in Phase 3.)

## 18. Controller continuous verification
- [x] Verify published state on schedule. (Phase 2: `controller_verification` APScheduler job → `ControllerAgent.verify_stale_published`.)
- [x] Detect stale published (SLA). (Phase 2 skeleton: logs one `agent_actions` finding; `alerts` wiring lands in Phase 3.)
- [x] Source hash mismatch check.
- [x] Audit row missing check.
- [x] Thread anchor orphaned check.
- [x] Sample revalidation of published records.
- [x] Post-publication recon drift check.
- [x] Open alerts and post to anchored threads; escalate critical.
- [x] Controller autonomously triggers a pipeline re-run on `STALE_PUBLISHED` (no Manager approval required)
- [x] Autonomous re-run logs exactly one `agent_actions` row with `agent_id = controller`
**Done when:** Controller job runs on schedule, detects at least one seeded anomaly, opens an alert, posts to the anchored thread, and — for `STALE_PUBLISHED` — autonomously re-runs the pipeline.

## 19. Frontend wiring (replace stub context with real data)
> Templates and route handlers were built in §1b with stub data. This
> section replaces stub context with real queries against Postgres and
> DuckDB. Do not rebuild templates; edit existing ones only where the real
> data shape requires it.
- [x] `/` Dashboard with KPI cards + inline analysis threads (all personas).
- [x] `/exceptions` queue (all).
- [x] `/exceptions/{id}` detail + thread (all).
- [x] `/runs` history (Analyst, Manager).
- [x] `/runs/{id}` detail + thread + approve/reject (Analyst, Manager).
- [x] `/scenarios` list + New Scenario (Analyst).
- [x] `/audit` agent_actions/approvals/publications filter by trace_id (Manager, Director).
- [x] `/observability` trace list + span tree + logs (all). (Phase 2.)
- [x] Persona selector in header on every page.
- [x] Base layout, HTMX partials, static CSS.
- [x] Baseline fixture seeded on boot (scenarios + published run + publication + run thread).
**Done when:** All 8 routes render with real data, and persona selection persists across pages.

## 20. Audit and compliance
- [x] `/audit` query filters by trace_id.
- [x] Ensure every agent action has `agent_actions` row and shared `trace_id`.
- [x] Display approvals and publications.

## 21. CI/CD (Level 3)
- [ ] `.github/workflows/test.yml`: lint, unit, integration on PRs and pushes.
- [ ] `.github/workflows/deploy-staging.yml`: push to `staging`.
- [ ] `.github/workflows/deploy-prod.yml`: push to `main` with manual approval via GitHub Environments.
- [ ] `.github/workflows/scenario-generate.yml`: `workflow_dispatch` run generator, upload R2, POST webhook.
- [ ] Integration tests use Postgres service container.
- [ ] `main` requires green tests + manual approval.

## 22. Infra and deployment
- [ ] `infra/Dockerfile`.
- [ ] `infra/render.yaml` (or Render config) for staging/prod services.
- [ ] Neon DB setup docs (staging/prod DBs).
- [ ] R2 bucket/prefix and lifecycle policy docs.
- [ ] Secrets documentation.
- [ ] `infra/docker-compose.yml` runs app + Postgres via `docker compose up`
- [ ] `README.md` documents `docker compose up` as the local single command

## 23. Testing
- [ ] Unit tests for validation rules SQL.
- [ ] Unit tests for reconciliation math.
- [ ] Unit tests for agent deterministic computations.
- [ ] Integration tests for routes with Postgres.
- [ ] Integration test for pipeline happy path.
- [ ] Test template fallback when LLM unavailable.
- [ ] Test: two alerts with same `(alert_type, anchor_id)` within 1 hour produce exactly one `alerts` row and one thread message (dedup).
- [ ] Test: every agent post produces exactly one `agent_actions` row sharing the same `trace_id` as the thread message.
- [ ] Integration tests mock R2 (localstack or filesystem fixture) and Groq (fake client returning fixture responses).
- [ ] Integration test asserts `trace_id` propagates from HTTP request through pipeline run to agent post.
- [ ] Test `/observability` route returns a trace list and renders a span tree for a known `trace_id`.
- [ ] Test persona selection persists across requests (cookie or `X-Persona` header) and is echoed in the header on every page.
- [ ] `pytest` (single command) runs all unit and integration tests and exits 0
- [ ] `README.md` documents the single test command
**Done when:** `pytest` (single command) runs all unit and integration tests and exits 0.

## 24. Documentation
- [ ] Update root `README.md`.
- [ ] Ensure `definitions.md` present.
- [ ] Document OTEL deviation (no external Grafana).
- [ ] Document persona switch and demo flow.
- [ ] Confirm spec filename is `SPEC.md` on disk and referenced as `SPEC.md` in `README.md` and `AGENTS.md`.
- [ ] Document the two-phase UI build (skeleton in §1b, wiring in §19) in `README.md` so reviewers understand template edits are expected.
- [ ] Root `README.md` describes (a) the problem, (b) system functionality, (c) expected behavior — not just a link to `SPEC.md`
- [ ] Update root `AGENTS.md` "Quick links" to include `SPEC.md`, `definitions.md`, `TASKS.md`, `backend/skills/`, `data/AGENTS.md`, and `data/README.md`

## 25. Success criteria verification (`SPEC.md §18`)
- [ ] Reviewer sees populated dashboard with `baseline_run` published.
- [ ] Navigation of `/exceptions`, `/runs`, `/audit`, `/observability` works without setup.
- [ ] Persona selection + posting in thread works.
- [ ] Analyst triggers "New Scenario"; appears in `/scenarios`.
- [ ] Analyst "Run Pipeline"; thread shows Orchestrator, DQ, DE, FA posts.
- [ ] Manager approves in run thread; published pointer updates.
- [ ] Controller alert fires on documented trigger.
- [ ] `/observability` shows trace spanning web request → pipeline → agent action.
- [ ] CI runs tests on PR; `main` requires approval.
- [ ] Every agent action has `agent_actions` row and shared `trace_id`.
- [ ] No file in the repo references the legacy plural spec filename; all spec references use `SPEC.md`.
- [ ] Root `AGENTS.md` links to `SPEC.md`, `definitions.md`, `TASKS.md`, and `backend/skills/`

## Non-goals guardrail
Do not implement anything in `SPEC.md §20`. If unsure, add to non-goals first.