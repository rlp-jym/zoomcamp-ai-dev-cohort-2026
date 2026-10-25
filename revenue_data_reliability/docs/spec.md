# Spec — Revenue Data Reliability Platform

Status: locked. All architectural decisions are recorded here. Coding agents
must not deviate without an explicit update to this file.

---

## 1. Overview

A full-stack application that ingests synthetic B2B-distribution revenue
data, validates it, reconciles billings to GL, surfaces exceptions, hosts
anchored discussion threads, and dispatches a team of agents to triage,
quantify, and propose remediation — with human approval at every gate.

The app is the product. The data generator under `data/` is a fixture
factory, not part of the runtime application.

---

## 2. Scope

### In scope
- Scenario creation (via generator, triggered from app)
- Pipeline run: validate → reconcile → produce exceptions
- Discussion anchored to runs, exceptions, and analysis slices
- Agent team: Orchestrator, DE, DQ, FA, Controller
- Human personas: Analyst, Manager, Director
- Alerting (in-app, 6 types)
- Observability (OTEL → Postgres, in-app viewer)
- Publication: Manager approves go-live; published pointer + quarantine overlay
- Controller continuous verification of published state

### Out of scope
- Forecasting, variance analysis engine (Project B)
- COGS, pricing, inventory, labor, fleet
- Auth (login, passwords, sessions) — personas are selected from a header dropdown
- Email/Slack alerting
- Multi-tenancy
- External Grafana/Jaeger integration (documented deviation)
- Budget as validated source (budget is reference only)

---

## 3. Personas

Seeded at boot. No authentication. Header selector sets the acting persona.

| ID | Type | Title | Role |
|---|---|---|---|
| `analyst` | human | FP&A Analyst | Owns runs; triggers pipeline; participates in threads |
| `manager` | human | FP&A Manager | Approves go-live; approves remediation |
| `director` | human | Director of FP&A | Critical escalation target |
| `orchestrator` | agent | Pipeline Orchestrator | Runs pipeline; posts start/finish; requests go-live |
| `de` | agent | Data Engineer | Proposes remediation (re-run, quarantine, reload) |
| `dq` | agent | Data Quality | Executes rules; posts validation results |
| `fa` | agent | Financial Analyst | Translates every defect into financial impact; may open analysis threads |
| `controller` | agent | Controller | Runtime first responder; verifies published state |

---

## 4. Architecture

### Storage split (critical)

| Store | Holds | Never holds |
|---|---|---|
| **R2 (S3-compatible)** | Parquet bundles per scenario, under `scenarios/<name>/` | App state |
| **Neon Postgres** | App state: runs, validations, reconciliations, exceptions, quarantines, approvals, publications, scenarios, discussions, messages, alerts, agent_actions, personas, rules, OTEL tables | Financial rows |

**Published data is derived at query time:**
`DuckDB.read_parquet(R2) − quarantine_filter − non-published runs`

### Backend

- FastAPI
- Jinja2 + HTMX (no JS framework, no build step)
- DuckDB reads Parquet from R2 (via `httpfs`)
- psycopg3, raw SQL
- APScheduler in-process for Controller checks only
- OTEL SDK with custom Postgres exporter

### Repo layout

```
revenue_data_reliability/
├── AGENTS.md
├── README.md
├── docs/
│   ├── spec.md
│   ├── tasks.md
│   ├── definitions.md
│   ├── operating-model.md
│   ├── demo.md
│   ├── architecture.md
│   ├── deployment.md
│   ├── challenges.md
│   └── backlog.md
├── frontend/
│   ├── templates/
│   └── static/
├── backend/
│   ├── main.py
│   ├── routes/
│   ├── services/
│   ├── teams/
│   │   ├── orchestrator.py
│   │   ├── de.py
│   │   ├── dq.py
│   │   ├── fa.py
│   │   └── controller.py
│   ├── skills/
│   │   ├── fa_impact_narrative/SKILL.md
│   │   ├── de_remediation_explanation/SKILL.md
│   │   ├── dq_validation_summary/SKILL.md
│   │   └── controller_triage_note/SKILL.md
│   └── db/
├── data/                # generator + runs (existing)
├── infra/               # Docker, Render config
├── observability/       # OTEL exporter, dashboards
├── tests/               # unit + integration
└── src/                 # uv_build package root
```

---

## 5. Data flow

```
Analyst clicks "New Scenario" → app calls GitHub Action (workflow_dispatch)
    → generator produces Parquet → uploads to R2 → webhooks app to register
    → scenario appears in /scenarios

Analyst clicks "Run Pipeline" on a scenario
    → Orchestrator posts "run started"
    → DQ runs 11 validation rules → posts summary
    → Reconciliation runs
    → Exceptions created (one per failed rule / material recon gap)
    → DE posts remediation proposal on each exception
    → FA posts financial impact on each exception
    → Manager approves go-live (run thread) or approves remediation
        (exception threads)
    → On go-live: publication row created; published pointer set

Controller (APScheduler, every N minutes)
    → Verifies published state
    → On anomaly: opens alert → posts to anchored thread → escalates if critical
```

---

## 6. Routes (8)

| # | Route | Anchor | Personas |
|---|---|---|---|
| 1 | `/` | Dashboard; analysis threads inline on KPI cards | all |
| 2 | `/exceptions` | Exception queue | all |
| 3 | `/exceptions/{id}` | Exception detail + thread | all |
| 4 | `/runs` | Run history | Analyst, Manager |
| 5 | `/runs/{id}` | Run detail + thread; approve/reject | Analyst, Manager |
| 6 | `/scenarios` | Scenario list + New Scenario button | Analyst |
| 7 | `/audit` | agent_actions, approvals, publications; filter by trace_id | Manager, Director |
| 8 | `/observability` | Trace list + span tree + logs | all |

Persona selector in header on every page.

---

## 7. Discussion model

Three anchor types, one table, one UI component.

| Anchor | Created by | Examples |
|---|---|---|
| `run` | Orchestrator on start | "Run started", "DQ: 47 rules, 3 failed", Manager approve |
| `exception` | DQ on detection | "DE remediation proposal", "FA impact", Manager approval |
| `analysis` | Analyst, FA, Manager | "Revenue Mar 2025 −12% vs budget, driver: X" |

Threads are ordered messages with `persona_id`, `trace_id`, optional
`evidence` JSON. Agent posts are visually distinguished (badge, muted
background).

---

## 8. Validation rules (11)

Each rule: `rule_id`, `description`, `severity`, `sql` (DuckDB over Parquet),
`expected_detection_rule`. Results stored in `validations`:
`(run_id, rule_id, status, summary_count, sampled_failures JSON)`.

| Rule ID | Catches |
|---|---|
| `VAL_FK_ITEM_EXISTS` | `orphaned_item_id` |
| `VAL_DUPLICATE_INVOICE_LINE` | `duplicate_invoice_line` |
| `VAL_FK_CUSTOMER_EXISTS` | `missing_customer_mapping` |
| `VAL_FRESHNESS_GL` | `stale_load` |
| `VAL_RECON_BILLINGS_GL` | `billings_gl_variance` |
| `VAL_RESTATEMENT_DETECTED` | `restatement` |
| `VAL_FX_RATE_EXISTS` | `fx_gap` |
| `VAL_FK_BACKORDER_ORDER_LINE` | `orphaned_backorder` |
| `VAL_FK_RETURN_SHIPMENT` | `phantom_return` |
| `VAL_AR_INVOICE_1TO1` | invariant |
| `VAL_ORDER_LINE_UNIQUE` | invariant |

---

## 9. Reconciliation

- Grain: `(run_id, period, account_id, item_category)` + top-N customers
- Billings from `invoice_lines`, GL from `gl_revenue`
- Variance % = (billings − gl) / gl
- Status: `pass` if within tolerance, `fail` otherwise
- Materiality threshold from config

---

## 10. Exceptions

One unified table, `type ∈ {validation, reconciliation, quarantine, controller_finding}`.

| Field | Purpose |
|---|---|
| `exception_id` | PK |
| `run_id` | Owning run |
| `type` | Validation / reconciliation / quarantine / controller_finding |
| `severity` | critical / high / medium / low |
| `period` | Month affected |
| `title` | Short human label |
| `status` | open / in_discussion / remediation_proposed / approved / resolved |
| `trace_id` | Correlates to OTEL spans |

---

## 11. Agent team

All agents write to their anchor thread and to `agent_actions`. All math is
deterministic Python; LLM is used only for prose.

| Agent | Writes | Executes | Permissions |
|---|---|---|---|
| Orchestrator | Start/finish messages on run thread | Runs pipeline; no data mutation | read-only on data |
| DQ | Validation summary, exceptions created | Runs rules | read-only on data |
| DE | Remediation proposal on exception thread | Executes only after Manager approval; writes `agent_actions` | bounded write (re-run, quarantine) |
| FA | Financial impact; may open analysis threads | None | read-only on data |
| Controller | Alerts, verification findings | None | read-only on published state |

### Approval gates

- **Go-live:** Manager approves in run thread → publication row created
- **Remediation:** Manager approves in exception thread → DE executes → logs `agent_actions`
- **Critical escalation:** Controller posts to Director in thread

### LLM usage

- Primary: Groq (env `GROQ_API_KEY`)
- Fallback: template render if key missing or call fails
- LLM is called for: triage note prose, thread summaries, FA's impact narrative
- LLM is never called for: numeric calculation, rule execution, action decision

### Skills (LLM prose layer only)

Four skills, one per agent that generates prose. Skills shape *how* a
message is written; they never shape *what* is computed or *which* action
is taken.

| Skill | Used by | Shapes |
|---|---|---|
| `fa_impact_narrative` | FA | Impact narrative on exception and analysis threads |
| `de_remediation_explanation` | DE | Explanation accompanying a remediation proposal |
| `dq_validation_summary` | DQ | Summary posted after a validation run |
| `controller_triage_note` | Controller | Triage note posted when an alert fires |

Each `SKILL.md` contains:

- Role framing for that agent persona
- The context fields the deterministic code will pass in (numbers, IDs,
  period, severity, evidence)
- Output structure and length
- Hard constraints: "Use only the provided values. Do not invent numbers.
  Do not recommend actions outside the versioned playbook."

**Boundary (non-negotiable):**

- Skills are loaded only when an LLM call is made.
- Skill output is prose only. It does not feed back into rule execution,
  remediation choice, or any numeric field.
- If the LLM is unavailable, the template fallback produces equivalent
  content from the same context object. The `SKILL.md` and the template
  must stay in sync; a mismatch is a bug.
- A skill cannot introduce a new remediation step, a new alert type, or a
  new rule. Those live in `spec.md` only.

**Loader:** one function `load_skill(name) -> str` reads
`backend/skills/<name>/SKILL.md`. No framework, no registry.

### Playbook (DE, bounded)

1. Re-run the same pipeline for the affected month
2. Quarantine N records with reason code
3. Reload FX rates from source (if applicable)
4. Open an issue-style note on the exception
5. Escalate to Manager

Each step is logged as one `agent_actions` row.

### Autonomous remediation (narrow)

One alert type is remediated autonomously, without Manager approval:

- **`STALE_PUBLISHED`:** Controller triggers a pipeline re-run for the
  affected month. This action is:
  - Read-consistent: re-validation only; no financial data mutated
  - Reversible: publication pointer unchanged until re-run passes
  - Logged: one `agent_actions` row with `agent_id = controller`
  - Reported: Controller posts a message on the alert thread

Controller does not gain broader write permissions. It triggers the same
pipeline action an Analyst would; no publication, approval, or financial
mutation is autonomous. All other remediation remains Manager-gated.

This satisfies the rubric requirement that "an agent wakes up on an alert
and fixes the issue" while keeping data-changing actions human-approved.

---



## 12. Alerting (6 types, in-app)

| Alert | Trigger | Severity | Remediation |
|---|---|---|---|
| `STALE_PUBLISHED` | Published run older than SLA | high | Controller auto-re-runs pipeline (see §11) |
| `SOURCE_HASH_MISMATCH` | R2 Parquet hash differs from registered manifest | critical | Thread + escalate |
| `AUDIT_ROW_MISSING` | Published action lacks `agent_actions` row | high | Thread + escalate |
| `THREAD_ANCHOR_ORPHANED` | Thread references deleted run/exception | medium | Thread + escalate |
| `PUBLISHED_RECORD_FAILS_REVALIDATION` | Controller re-runs sample, finds failures | critical | Thread + escalate |
| `RECON_DRIFT` | Post-publication billings vs GL exceeds tolerance | critical | Thread + escalate |

- Dedup: `(alert_type, anchor_id)` in 1-hour window
- Destinations: `alerts` row + Controller message on the anchor thread + dashboard badge
- Critical: escalate to Director via thread message

---

## 13. Observability

- OTEL SDK auto-instruments FastAPI, psycopg3, boto3, DuckDB
- Custom Postgres exporter batches to `otel_spans`, `otel_logs`, `otel_metrics`
- `/observability` renders trace list + span tree + linked logs
- Retention: spans/logs older than 30 days deleted (job in APScheduler)
- No PII in telemetry; no credentials
- **Deliberate deviation from course default** documented in this spec: no external Grafana; self-hosted OTEL data viewed in-app

---

## 14. Deployment

- **Platform:** Render free tier
- **App:** two services — `staging` (branch: `staging`), `prod` (branch: `main`)
- **DB:** Neon free tier — one project, two databases (`staging`, `prod`)
- **Object storage:** Cloudflare R2, one bucket, `scenarios/<name>/` prefixes
- **Secrets:** Render env vars for `DATABASE_URL`, `R2_*`, `GROQ_API_KEY`, `GH_TOKEN`, `WEBHOOK_TOKEN`
- **DB schema:** `schema.sql` idempotent on boot (`CREATE TABLE IF NOT EXISTS`)
- **Backfill:** on first boot, if `scenarios` empty, trigger the GitHub Action to generate `baseline_run` with seed=9, then wait for webhook
- **Local run:** `docker compose up` starts app + Postgres in one command. Documented in `README.md`.

---

## 15. CI/CD (Level 3)

| Workflow | Trigger | Action |
|---|---|---|
| `test.yml` | PRs, all pushes | Lint, unit, integration |
| `deploy-staging.yml` | Push to `staging` | Deploy to staging |
| `deploy-prod.yml` | Push to `main` | Manual approval via GitHub Environments, then deploy |
| `scenario-generate.yml` | `workflow_dispatch` | Run generator, upload to R2, POST to app webhook |

- Integration tests use Postgres service container
- `main` requires green tests + manual approval to deploy
- Rubric L3 satisfied

---

## 16. Tech stack (locked)

| Layer | Choice |
|---|---|
| Backend | FastAPI (Python 3.11+) |
| Templates | Jinja2 |
| Interactivity | HTMX |
| Parquet query | DuckDB (`httpfs` for R2) |
| Postgres client | psycopg3, raw SQL |
| Scheduler | APScheduler in-process |
| Telemetry | opentelemetry-sdk + custom exporter |
| LLM | Groq + template fallback |
| Object storage | Cloudflare R2 |
| CI/CD | GitHub Actions |
| Deploy | Render |

---

## 17. Constraints and limitations

- Render free = 512MB RAM, ephemeral disk, no background workers
- Neon free = 1GB total; app state stays under ~50MB via state-only model
- R2 free = 10GB; ~20 scenarios max; lifecycle policy required
- SQLite not used — PostgreSQL required due to discussion write contention
- No auth — personas selected from header; acceptable for demo, documented
- No migrations framework — schema changes require `schema.sql` edits
- In-process APScheduler competes with web requests — acceptable at demo scale
- LLM may be unavailable — template fallback preserves function

---

## 18. Success criteria

- End user visits the URL, loads a seed, and sees a populated dashboard
- End user navigates `/exceptions`, `/runs`, `/audit`, `/observability` without setup
- End user selects a persona in the header and can post in a thread
- Analyst persona can trigger "New Scenario"; new scenario appears in `/scenarios`
- Analyst persona can "Run Pipeline"; thread shows Orchestrator, DQ, DE, FA posts
- Manager persona can approve in run thread; published pointer updates
- Controller alert fires on a documented trigger (e.g., stale published)
- `/observability` shows at least one trace spanning web request → pipeline → agent action
- CI runs tests on PR; `main` requires approval
- Every agent action has an `agent_actions` row and shares a `trace_id`

---

## 19. Prerequisites before build

- [ ] Generator updated to emit `budget` table (reference-only)
- [ ] `baseline_run` regenerated with seed=9 (16 tables)
- [ ] `data/AGENTS.md`, `data/TASKS.md`, `data/SOURCES.md` updated
- [ ] `docs/definitions.md` written (revenue, billings, DSO, fill rate, materiality)
- [ ] Root `README.md` updated with project overview + link to `docs/spec.md`
- [ ] Root `README.md` describes (a) the problem, (b) system functionality, (c) expected behavior

---

## 20. Explicit non-goals

If a coding agent is unsure whether to add something, it goes here first.
If listed here, do not build it.

- User registration, login, sessions, OAuth
- Email or Slack notifications
- Mobile-responsive redesign beyond basic CSS
- Dark mode
- Multi-tenant organization isolation
- Data export to Excel
- Custom dashboard builder
- Forecasting
- Budget authoring (reference only)
- Variance engine beyond reconciliation tolerance
- Prompt engineering framework or agent chain library
- Custom ML models
- WebSocket live updates (HTMX polling is sufficient)
- Skills that compute or decide anything (skills are prose-only)
- Skill framework, registry, or discovery beyond `load_skill(name)`