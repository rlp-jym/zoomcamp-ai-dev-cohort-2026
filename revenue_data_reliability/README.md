# Revenue Data Reliability Platform

## The Problem

FP&A guides business decisions on capital allocation and quarterly strategy. This requires timely, reliable data above all else. In practice, numbers get delayed by manual effort, such as reconciling billings, chasing FX variances, and correcting restatements. Analysts spend the close assembling data rather than offering insights. While audit reporting focuses on absolute accuracy, FP&A needs a decision-grade number delivered on time, with enough context to move forward.

## The Value

| Challenge | Cost | Solution |
|---|---|---|
| Manual data cleanup | Days lost matching numbers | Automated, fast validation |
| Chasing perfection | Delayed market reaction | Tolerance-based publishing |
| Dispersed context | Email sign-offs and zero history | Central logs and run-linked discussions |
| Poor visibility | Restatements and lost trust | Simple audit trail with gatekeeper approval |
| Data drift | Unchecked post-close changes | Background monitoring and alerts |

## Scope & Focus

- **Platform:** Full-stack architecture, persistent Postgres, agent workflows, and observability.
- **FP&A Domain:** 12 validation rules, billings-vs-GL reconciliation, and gated release approvals.
- **Scope Note:** Focuses specifically on revenue streams to keep the demo clean and maintainable.

The discussion thread is the core interaction; the pipeline exists to give it something worth discussing.

## Live Demo

| Environment | URL | Notes |
|---|---|---|
| Production | https://revenue-platform-prod.onrender.com | `main`; empty until a dataset is loaded |
| Staging | https://revenue-platform-staging.onrender.com | `staging`; pre-loaded demo data |
| Health | https://revenue-platform-prod.onrender.com/health | `{"status":"ok"}` |

## Start Here

| # | Page (URL) | Persona | Action | Expected |
|---|---|---|---|---|
| 1 | Validation (`/runs`) | FP&A Analyst | Load Dataset | Dataset appears |
| 2 | Validation (`/runs`) | FP&A Analyst | Validate | 12 rules run |
| 3 | Validation (`/runs/{id}`) | FP&A Analyst | Review results | Rule table + publication block |
| 4 | Data Issues (`/exceptions`) | FP&A Analyst / FP&A Manager | Review open issues | Queue with period and severity |
| 5 | Validation (`/runs/{id}`) | FP&A Manager | Approve Go-Live | Publication created |
| 6 | Dashboard (`/`) | Any | Open Dashboard | Target Attainment, charts, threads |

## App Personas

| Role (ID) | Category | Responsibilities |
|---|---|---|
| **FP&A Analyst** (`analyst`) | Human | Loads datasets, triggers validation |
| **FP&A Manager** (`manager`) | Human | Approves releases and remediation proposals |
| **Director of FP&A** (`director`) | Human | Controls demo data resets |
| **Pipeline Orchestrator** (`orchestrator`) | Agent | Executes pipeline flow and posts start/finish status |
| **Data Quality** (`dq`) | Agent | Runs 12 validation rules and posts validation summaries |
| **Data Engineer** (`de`) | Agent | Generates remediation options; executes quarantine upon approval |
| **Financial Impact** (`fa`) | Agent | Calculates and writes impact narratives for open issues |
| **Controller** (`controller`) | Agent | Verifies published state, manages alerts, and triggers escalations |

## Expected Workflow

```mermaid
graph TD
    subgraph p1["Phase 1: Preparation & Execution"]
        A["1. Load Dataset (Analyst)"] --> B["2. Run Validation Rules (Analyst & Agents)"]
    end

    subgraph p2["Phase 2: Review & Resolution"]
        C["3. Review Findings & Blocks (Analyst & Agents)"] --> D["4. Resolve Open Issues (Manager)"]
    end

    subgraph p3["Phase 3: Release & Publication"]
        E["5. Approve Go-Live (Manager)"] --> F["6. Dashboard Publishes (automatic)"]
    end

    subgraph p4["Phase 4: Ongoing Collaboration"]
        G["7. Anchored Discussion Thread (All Personas)"]
    end

    B --> C
    D --> E
    F --> G
```

The priority order is deliberate: timeliness, accuracy, then auditability.

## Core Principles

| Principle | How It Functions |
| --- | --- |
| Speed first | Accepts tolerable variance so decisions are not delayed |
| Manager sign-off | Human approval required for all fixes and go-live decisions |
| Continuous review | Background controller monitors data freshness and flags issues |
| Restricted actions | Auto-triggers revalidation only; cannot republish on its own |
| Immutable raw data | Isolates issues via quarantine without touching source files |

See [`docs/operating-model.md`](docs/operating-model.md).

## Sample Datasets

| Seed | Scenario | Description | Storage Path |
| --- | --- | --- | --- |
| 101 | Neutral | Flat performance, misses target | `scenarios/seed_101/` |
| 102 | Bullish | Outperforms target | `scenarios/seed_102/` |
| 103 | Bearish | Declining performance | `scenarios/seed_103/` |

These are synthetic 12-month pre-generated datasets. The generator was removed after the three seeds were produced; the app only registers and reads them. If go-live is blocked, clear open items under **Data Issues** (`/exceptions`) first.

## Platform Features

| Capability | How It Works |
| --- | --- |
| Validation | 12 DuckDB rules running against Filebase-hosted Parquet data |
| Reconciliation | Automated billings vs GL matching by period, account, and category |
| Exception Queue | Tracks monthly rule failures and keeps current period issues active |
| Agent Support | Dedicated agents handle pipeline flows, data quality, and impact checks |
| Access Control | Gated publishing workflow requiring FP&A Manager sign-off |
| Observability | Traces, logs, and metrics in Postgres with an in-app viewer; `/audit` holds the action ledger |
| Reporting | Live dashboard for variance, revenue growth, and target attainment |

## Architecture

```mermaid
flowchart LR
    subgraph Frontend
        U[Browser + HTMX]
    end

    subgraph App["FastAPI Application"]
        direction TB
        F[Routes] -->|dispatch| S[Services]
        S -->|invoke| A[Agent Team]
        SCH[APScheduler] -->|verify every 15 min| A
    end

    subgraph Data["Data Layer"]
        direction TB
        P[(PostgreSQL / Neon)]
        D[DuckDB Query Engine]
        R[(Filebase S3)]
    end

    L[Groq LLM]
    O[OpenTelemetry]

    U -->|HTTP / HTMX| F
    F -->|Jinja HTML| U
    S -->|read / write| P
    S -.->|SQL scans| D
    D -->|read Parquet| R
    A -.->|prompt| L
    A -->|messages / actions| P
    F -->|spans / logs| O
    O -->|export| P

    linkStyle 0 stroke:#94a3b8,stroke-width:1px
    linkStyle 3,4 stroke:#2563eb,stroke-width:1px
    linkStyle 1,2 stroke:#7c3aed,stroke-width:1px
    linkStyle 5,7,9 stroke:#16a34a,stroke-width:1px
    linkStyle 6,8 stroke:#ea580c,stroke-width:1px
    linkStyle 10,11 stroke:#94a3b8,stroke-width:1px,stroke-dasharray: 2 3
```

**Footnotes**

- **Routes** (`backend/routes/`): page handlers, form actions, approval gates, and thread endpoints.
- **Frontend → Routes**: page loads, HTMX swaps, and form submits all arrive as HTTP requests.
- **Routes → Frontend**: Jinja renders the full page or an HTMX partial; that HTML is the only response path.
- **Routes → Services**: routes dispatch to services, which own the data and agent work.
- **Routes → OpenTelemetry**: every request emits a span/log; OpenTelemetry exports it to PostgreSQL / Neon.

See [`docs/architecture.md`](docs/architecture.md).

## Repository Structure

| Directory | Scope |
| --- | --- |
| `backend/` | FastAPI routes, domain services, agents, and storage |
| `frontend/` | Jinja templates, HTMX interactivity, and styling |
| `infra/` | Dockerfile, Render blueprint, and provider notes |
| `observability/` | OpenTelemetry setup and Postgres exporter |
| `tests/` | Unit and integration tests |
| `docs/` | System architecture, operating model, and project guides |
| `src/` | Python package root (`uv_build`) |

## Run Locally

```bash
cp .env.example .env          # optional; Windows: Copy-Item .env.example .env
docker compose up --build

```
- App: http://localhost:8000
- Health: `/health`
- Postgres: `localhost:5432`
- `.env` supplies Filebase (`R2_*`) and Groq credentials; without it the app starts with local Postgres and empty storage.

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

## CI/CD

| Workflow | Trigger | Action |
| --- | --- | --- |
| `test.yml` | PRs and pushes | Lint + tests (Postgres service) |
| `deploy-staging.yml` | Push to `staging` | Tests, then Render deploy |
| `deploy-prod.yml` | Push to `main` | Manual approval, then Render deploy |

See [`docs/deployment.md`](docs/deployment.md).

## Known Limits

| Limit | Mitigation |
| --- | --- |
| Render 512 MB | 12-month window, DuckDB 200 MB / 1 thread, local Parquet cache |
| Free Postgres | State-only schema; 30-day telemetry retention |
| No auth | Persona selector for demo; documented non-goal |
| LLM optional | Template fallback when `GROQ_API_KEY` is empty |

## Documentation

| Document | Purpose |
| --- | --- |
| [`docs/spec.md`](docs/spec.md) | Locked architecture and scope |
| [`docs/tasks.md`](docs/tasks.md) | Public task tracker; acceptance criteria per section |
| [`docs/definitions.md`](docs/definitions.md) | Metric definitions and materiality |
| [`docs/operating-model.md`](docs/operating-model.md) | Timeliness/accuracy trade-off |
| [`docs/demo.md`](docs/demo.md) | End-user walkthrough |
| [`docs/architecture.md`](docs/architecture.md) | System flow and agents |
| [`docs/deployment.md`](docs/deployment.md) | Environments, CI/CD, rollback |
| [`docs/challenges.md`](docs/challenges.md) | Engineering challenges and workarounds |
| [`docs/traceability.md`](docs/traceability.md) | Rubric and build evidence map |

Task sections carry "Done when" acceptance criteria. The checkbox history and the commit history serve as primary evidence of completion.