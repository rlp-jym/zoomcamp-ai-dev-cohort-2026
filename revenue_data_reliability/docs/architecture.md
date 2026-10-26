# Architecture

Browser + HTMX talk to FastAPI. Routes dispatch to services and agents. Postgres
holds state, DuckDB reads Parquet from Filebase, and OpenTelemetry writes back
to Postgres.

## Request Flow

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

## Stores

| Store | Holds | Notes |
|---|---|---|
| PostgreSQL / Neon | Personas, datasets, runs, validations, reconciliations, exceptions, quarantines, discussions/messages, approvals, publications, alerts, `agent_actions`, `dashboard_cache`, `otel_*` | System of record |
| DuckDB | — | In-process query engine over Parquet; no persistent state |
| Filebase S3 | `scenarios/<dataset>/*.parquet` + `manifest.json` | Immutable source bundle; env vars keep the `R2_` prefix |
| Local disk | Per-dataset Parquet cache | 800 MB cap; oldest folder evicted first; validation scans the latest 12 months |

## Pipeline

```mermaid
sequenceDiagram
  participant A as FP&A Analyst
  participant O as Pipeline Orchestrator
  participant DQ as Data Quality
  participant FA as Financial Impact Agent
  participant M as FP&A Manager
  participant PUB as Publication

  A->>O: Validate dataset
  O->>O: Run 12 rules + reconcile billings vs GL
  O->>DQ: Hand off results
  DQ-->>O: Summary posted to run thread
  O->>FA: Hand off open issues
  FA-->>O: Impact narrative posted
  O-->>A: Run complete
  M->>PUB: Approve Go-Live
  PUB->>PUB: Publication row + published pointer
  PUB-->>M: Dashboard cache rebuild started
```

Remediation is not part of the pipeline. The Manager or DE requests a proposal
from Data Issues (`/exceptions/{id}`); the DE executes the quarantine, either
directly or after the Manager approves the remediation.

## Agent Team

| Agent | Code | Trigger | Writes |
|---|---|---|---|
| Pipeline Orchestrator | `services/orchestrator.py` | Analyst clicks Validate; Controller rerun | Run status, start/finish messages, run trace |
| Data Quality | `services/dq.py` | Every pipeline run | Validation summary message + action |
| Financial Impact Agent | `teams/fa.py` | Every pipeline run | Impact narrative per open issue |
| Data Engineer | `teams/de.py` | Manager/DE request; approved remediation | Proposal, quarantine rows |
| Controller | `teams/controller.py` | APScheduler, every 15 minutes | Alerts, triage notes, revalidation runs |

## Trace Propagation

| Stage | Trace |
|---|---|
| HTTP request | FastAPI server span |
| UI-triggered pipeline | New root `pipeline.run` span in a daemon thread; `runs.trace_id` points at it |
| Controller cycle | `controller.verification_job` span; its autonomous rerun is a child |
| Agent action | `agent_actions.trace_id` |
| Thread message | `messages.trace_id` |
| Demo reset | Both audit rows share the `POST /runs/reset` trace |

A UI-triggered run is a separate trace from the click that started it: the
request returns immediately, and the pipeline runs in a background thread.

## Runtime and Offline

| Component | Runtime? | Role |
|---|---|---|
| FastAPI | Yes | Serves the app |
| Filebase `scenarios/<dataset>/*.parquet` | Yes | Source of Parquet for validation and dashboard |
| `data/` generator | No | Historical fixture factory; produced the fixed seeds |
| `run_generator.*` | No | Local orchestration; kept for reproducibility |
| `upload.py` | No | Uploads Parquet to Filebase; used by the manual workflow |
| `scenario-generate.yml` | No | Manual workflow; disabled in GitHub Actions |

## Deviations

| Deviation | Reason |
|---|---|
| OTel stored in Postgres, viewed in-app | No external Grafana/Jaeger; documented non-goal |
| Persona selector instead of auth | Demo scope; documented non-goal |
| Baseline fixture retired | Generated datasets carry their own runs and publication pointers |
| Only FastAPI auto-instrumented | Telemetry volume stays inside the free Postgres tier |
| Scenarios nav hidden | Route remains for forward-looking analysis; not part of the demo path |
| Remediation is human-triggered | The pipeline no longer auto-proposes; Manager/DE requests it from Data Issues |
| UI-triggered runs get their own trace | The request returns immediately; the pipeline runs in a daemon thread |

See [spec.md](spec.md) §4 for the locked component contract. This page reflects
runtime behavior where it diverges from §5.
