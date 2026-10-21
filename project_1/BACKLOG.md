# Backlog — Page & Behavior Verification of Current Features

Scope: only behaviors that exist in the running app today. No gap/absence audits,
no CI/CD or infra checks, no future-feature expectations.

## Global
- [x] Persona selector persists across all pages via cookie and reflects in header.
- [x] Header nav renders the 6 top-level routes (Dashboard, Scenarios, Validation, Data Issues, Audit, Observability) on every page, grouped as analysis first then the validation pipeline.
- [x] Agent posts visually distinguished (badge, muted background) in thread partial.
- [x] Every agent action is logged in `agent_actions` with a `trace_id` matching its thread message.
- [x] `/health` returns `{status: ok}`.

## `/` Dashboard
- [x] Renders from the cached payload after a scheduler refresh; shows cache timestamp.
- [x] Alert banner + badge reflect open alerts and count (banner lists latest 5).
- [x] Empty state + "Refresh KPIs now" button when no published dataset/cache.
- [x] KPI card grid removed in favour of charts + threads; Open Data Issues survives as a threadless stat strip (red if > 0, green if 0, bold) above Target Attainment.
- [x] 4 Chart.js charts render from the `charts` payload (Revenue/Billings/Target, Variances by Category, Month-over-Month Growth, Billings by Customer Segment as bars) plus a Target Attainment progress bar (top of page, no thread, title carries the latest month). The General Ledger series is drawn once, not once per chart; the run-rate projection is gone (projections live under Scenarios).
- [x] Posting a message to a `kpi-*` analysis thread updates via HTMX partial.
- [x] Manual `/dashboard/refresh` recomputes the cache without scanning S3 in the request path.

## `/exceptions`
- [x] Lists all exceptions with id, type, severity, period, title, status, trace.
- [x] Each row links to `/exceptions/{id}`.

## `/exceptions/{id}`
- [x] Shows metadata (type, severity, period, status, trace, title).
- [x] Validation exception shows sampled failures as JSON.
- [x] Reconciliation exception shows monthly recon rows (period, account, category, billings, GL, variance %, status).
- [x] Quarantine records table renders with reason code, keys, creator, timestamp.
- [x] Manager sees Approve button only when status != resolved; DE sees Quarantine button only when status != resolved.
- [x] Approve sets status to resolved, DE logs `remediation_executed`, posts a system message.
- [x] Quarantine inserts a `quarantines` row, DE logs `quarantine_executed`, posts a message, resolves the exception.
- [x] Thread renders and HTMX post works.

## `/runs`
- [x] Lists runs with id, scenario, status, started, duration, published flag.
- [x] Each row links to `/runs/{id}`.

## `/runs/{id}`
- [x] Shows run metadata, validations table (rule, status, count, severity, description).
- [x] Publication block shows publication_id, published_at, pointer, published_by when published.
- [x] Manager sees Approve Go-Live button only for completed, unpublished runs.
- [x] Non-manager sees "Go-Live approval requires the Manager persona."
- [x] Approve creates a publication row, moves the published pointer, posts a thread message, writes an approvals row.
- [x] Reject sets status to rejected, writes an approvals row, posts a message (no persona gate).
- [x] Thread renders and HTMX post works. (thread renders; HTMX post not exercised, pages-only pass)

## `/scenarios`
- [x] Lists scenarios with name, status, tables, seed, created_at.
- [ ] Run Pipeline button triggers the pipeline and redirects to the run detail page. (removed — pipeline runs via script only)
- [x] When `baseline_run` Parquet keys exist in R2, `ensure_baseline_registered` registers the scenario row on page load.

## `/audit`
- [x] Renders agent_actions, approvals, publications.
- [x] `?trace_id=` filters actions and approvals by trace.
- [x] Payload column renders as JSON (truncated).

## `/observability`
- [x] Trace list renders; selecting a trace shows its span tree and linked logs.
- [x] `?trace_id=` selects the trace.
- [x] Summary counts render.

## Pipeline behavior
- [x] Clicking Run Pipeline creates a run row and posts an Orchestrator "run started" message.
- [x] All 11 rules execute; results stored in `validations`.
- [x] Reconciliation rows stored; material gaps create exceptions.
- [x] One exception per affected month per failed rule.
- [x] Data Issue lifecycle: only the latest data period stays `open`; earlier periods are inserted `resolved` so the list is a pending queue (≤ ~12 open).
- [x] DQ posts a validation summary to the run thread.
- [x] DE posts a remediation proposal per open exception.
- [x] FA posts an impact narrative per open exception.
- [x] Run ends completed with counts; Orchestrator posts a "run finished" message.
- [ ] On exception, run is marked failed and a failure message is posted. (not exercised — needs a forced failure; code path exists in orchestrator.run_pipeline with status='failed' and try/except)

## Alerts & Controller
- [ ] When a publication is older than `controller_stale_hours`, Controller opens a `STALE_PUBLISHED` alert with row + thread message + dashboard badge. (not exercised — current publication is fresh; no STALE_PUBLISHED alerts in DB)
- [x] Alert creates an `alerts` row + Controller triage message on the anchor thread. (verified: 139 open alerts, 100 controller triage messages; controller persona has 100 messages)
- [ ] Critical alert types that pass `escalate=True` (source hash mismatch, published-record revalidation failure, recon drift) escalate to Director via a thread message. (not exercised — no critical alert has fired in the current data; `_escalate_to_director` exists in controller.py)
- [x] Dedup: same `(alert_type, anchor_id)` within 1 hour yields one row and one thread message. (verified: controller payloads carry `"deduplicated": true`)
- [ ] `STALE_PUBLISHED` triggers an autonomous pipeline re-run, logging one `autonomous_re_run` `agent_actions` row with `agent_id = controller` (plus the alert rows). (not exercised — no stale publication in current data)
- [x] Controller runs all 6 checks per verification cycle (stale published, source hash, audit row, thread anchor, revalidation, recon drift). (verified: `run_controller_verification` iterates all 6; 4 alert types raised across 663 controller actions)

## Publication & quarantine
- [x] Published pointer uniqueness: exactly one published run per scenario. (verified: 1 published run for baseline_run)
- [x] Quarantine filter excludes quarantined records from the published-data query. (verified by code: `publications.get_published_data_query` calls `quarantines.quarantined_invoice_line_ids`; not exercised end-to-end — 0 quarantines in the current dataset)
- [x] Controller source-hash check compares R2 Parquet hashes to the registered manifest. (verified by code: `check_source_hash_mismatch` calls `verify_manifest`; runs each cycle, cached per manifest; no mismatch in current data)

## Observability
- [x] Requests produce traces visible in `/observability` with spans and linked logs. (verified: 18,294 spans, 188 logs, page renders 200 with trace selection)
- [x] Retention job deletes spans/logs/metrics older than the configured window (default 30 days). (verified by code: `run_retention` scheduled every 24h in scheduler, deletes from all 3 otel tables; not exercised by age — no data older than 30 days in the current window)

## Webhook
- [x] `POST /api/scenarios/register` with a valid `WEBHOOK_TOKEN` registers/updates a scenario row. (verified: 200 + registered with dev-webhook-token; 401 without)

## Persona
- [x] `POST /persona` sets the cookie and redirects to the referer. (verified: 303 + Set-Cookie persona=manager; HttpOnly; SameSite=lax)

## Load times (local, warm cache, single request)
Measured 2026-10-21 against the running app (published run 39, 139 open alerts,
18,294 otel spans). All reads are served from Postgres/R2; the dashboard reads
the cached payload (no S3 scan in the request path).

| Route | Status | ms | bytes |
|---|---|---|---|
| `/` (dashboard) | 200 | 3204 | 13972 |
| `/exceptions` | 200 | 4253 | 7385 |
| `/exceptions/7471` | 200 | 5286 | 6064 |
| `/runs` | 200 | 1108 | 4938 |
| `/runs/39` | 200 | 5525 | 5937 |
| `/scenarios` | 200 | 1073 | 2874 |
| `/audit` | 200 | 3641 | 99770 |
| `/audit?trace_id=...` | 200 | 3165 | 4923 |
| `/observability` | 200 | 4884 | 9802 |
| `/observability?trace_id=...` | 200 | 4475 | 10181 |
| `/health` | 200 | 2 | 15 |

Notes:
- `/health` is the only sub-100ms route. Page routes are 1-5.5s, which is slow
  for a local app; the dominant cost is the remote Postgres (Neon) round-trip
  plus per-request template rendering, not S3. Dashboard cache refresh is the
  heavy path (~100s) and runs in the scheduler, not the request path.
- `/runs/39` (5.5s) and `/exceptions/{id}` (5.3s) are the slowest per-byte;
  both do several sequential DB round-trips. Candidate for batching/caching if
  load time becomes a priority.
- `/audit` is 99KB because it renders the full agent_actions table; the
  `?trace_id=` filter cuts it to ~5KB and ~3.2s. The default (unfiltered) view
  is the expensive one.
- Not exercised in this pass (needs setup/conditions not present): inducing a
  failed run, STALE_PUBLISHED alert + autonomous re-run, critical-alert
  escalation to Director, quarantine end-to-end (0 quarantines in DB), and the
  30-day retention deletion (no data older than 30 days). Flagged below.