# Operating Model

## Objective

| Priority | Choice |
|---|---|
| 1 | **Timeliness** — publish data good enough to act on this month |
| 2 | **Accuracy** — bounded by tolerance, not zero variance |
| 3 | **Auditability** — every action logged, every publication human-approved |

This is an FP&A simulation, not an audit system. Waiting for perfect data is a
failure mode; acting on data outside tolerance is a different one.

## Tolerance, Not Perfection

| Control | Behavior |
|---|---|
| Validation rules | Fire when variance exceeds the configured tolerance |
| Reconciliation | Billings vs GL at `(period, account_id, item_category)`; material gaps raise exceptions |
| Data Issues | One per affected month per failed rule; the latest period stays `open` |
| Publication | Blocked while open data issues remain |

## Controller

| Responsibility | Detail |
|---|---|
| Freshness SLA | `CONTROLLER_STALE_HOURS` (default 24h) |
| Continuous verification | Six checks every `CONTROLLER_INTERVAL_MINUTES` (default 15) |
| Alerting | Six in-app types; one-hour dedup; dashboard badge |
| Escalation | Critical alerts post to the Director of FP&A |
| Autonomous action | `STALE_PUBLISHED` → revalidation run only |
| Not autonomous | No publication, approval, or financial mutation |

```mermaid
flowchart LR
  A[Alert] --> B{Critical?}
  B -- yes --> C[Escalate to Director of FP&A]
  B -- no --> D[Controller triage]
  A --> E{Stale published?}
  E -- yes --> F[Revalidation run]
  E -- no --> D
```

The Controller is the counterweight to timeliness: it enforces freshness and
escalates drift, while publication stays FP&A Manager-gated.

## Governance

| Gate | Approver | Effect |
|---|---|---|
| Go-live | FP&A Manager | Publication row + dashboard pointer |
| Remediation | FP&A Manager | Data Engineer executes quarantine or re-run |
| Critical escalation | Director of FP&A | Informed on the anchor thread |
| Demo reset | Director of FP&A | Deletes non-baseline data |
