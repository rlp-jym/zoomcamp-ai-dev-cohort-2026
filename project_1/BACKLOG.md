# Backlog — Page & Behavior Verification of Current Features

Scope: only behaviors that exist in the running app today. No gap/absence audits,
no CI/CD or infra checks, no future-feature expectations.

## Global
- [x] Persona selector persists across all pages via cookie and reflects in header.
- [x] Header nav renders the 6 top-level routes (Dashboard, Exceptions, Runs, Scenarios, Audit, Observability) on every page.
- [x] Agent posts visually distinguished (badge, muted background) in thread partial.
- [x] Every agent action is logged in `agent_actions` with a `trace_id` matching its thread message.
- [x] `/health` returns `{status: ok}`.

## `/` Dashboard
- [x] Renders from the cached payload after a scheduler refresh; shows cache timestamp.
- [x] Alert banner + badge reflect open alerts and count (banner lists latest 5).
- [x] Empty state + "Refresh KPIs now" button when no published dataset/cache.
- [x] KPI cards render (3 when no publication, 6 when published) with values/deltas; each has an inline analysis thread.
- [x] 4 Chart.js charts render from the `charts` payload (revenue vs budget, variance by category, segments, KPI trends).
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
- [ ] Lists runs with id, scenario, status, started, duration, published flag.
- [ ] Each row links to `/runs/{id}`.

## `/runs/{id}`
- [ ] Shows run metadata, validations table (rule, status, count, severity, description).
- [ ] Publication block shows publication_id, published_at, pointer, published_by when published.
- [ ] Manager sees Approve Go-Live button only for completed, unpublished runs.
- [ ] Non-manager sees "Go-Live approval requires the Manager persona."
- [ ] Approve creates a publication row, moves the published pointer, posts a thread message, writes an approvals row.
- [ ] Reject sets status to rejected, writes an approvals row, posts a message (no persona gate).
- [ ] Thread renders and HTMX post works.

## `/scenarios`
- [ ] Lists scenarios with name, status, tables, seed, created_at.
- [ ] Run Pipeline button triggers the pipeline and redirects to the run detail page.
- [ ] When `baseline_run` Parquet keys exist in R2, `ensure_baseline_registered` registers the scenario row on page load.

## `/audit`
- [ ] Renders agent_actions, approvals, publications.
- [ ] `?trace_id=` filters actions and approvals by trace.
- [ ] Payload column renders as JSON (truncated).

## `/observability`
- [ ] Trace list renders; selecting a trace shows its span tree and linked logs.
- [ ] `?trace_id=` selects the trace.
- [ ] Summary counts render.

## Pipeline behavior
- [x] Clicking Run Pipeline creates a run row and posts an Orchestrator "run started" message.
- [x] All 11 rules execute; results stored in `validations`.
- [x] Reconciliation rows stored; material gaps create exceptions.
- [x] One exception per affected month per failed rule.
- [x] DQ posts a validation summary to the run thread.
- [ ] DE posts a remediation proposal per open exception. (capped at `MAX_AGENT_MESSAGES_PER_RUN`)
- [ ] FA posts an impact narrative per open exception. (capped at `MAX_AGENT_MESSAGES_PER_RUN`)
- [x] Run ends completed with counts; Orchestrator posts a "run finished" message.
- [ ] On exception, run is marked failed and a failure message is posted.

## Alerts & Controller
- [ ] When a publication is older than `controller_stale_hours`, Controller opens a `STALE_PUBLISHED` alert with row + thread message + dashboard badge.
- [ ] Alert creates an `alerts` row + Controller triage message on the anchor thread.
- [ ] Critical alert types that pass `escalate=True` (source hash mismatch, published-record revalidation failure, recon drift) escalate to Director via a thread message.
- [ ] Dedup: same `(alert_type, anchor_id)` within 1 hour yields one row and one thread message.
- [ ] `STALE_PUBLISHED` triggers an autonomous pipeline re-run, logging one `autonomous_re_run` `agent_actions` row with `agent_id = controller` (plus the alert rows).
- [ ] Controller runs all 6 checks per verification cycle (stale published, source hash, audit row, thread anchor, revalidation, recon drift).

## Publication & quarantine
- [ ] Published pointer uniqueness: exactly one published run per scenario.
- [ ] Quarantine filter excludes quarantined records from the published-data query.
- [ ] Controller source-hash check compares R2 Parquet hashes to the registered manifest.

## Observability
- [ ] Requests produce traces visible in `/observability` with spans and linked logs.
- [ ] Retention job deletes spans/logs/metrics older than the configured window (default 30 days).

## Webhook
- [ ] `POST /api/scenarios/register` with a valid `WEBHOOK_TOKEN` registers/updates a scenario row.

## Persona
- [ ] `POST /persona` sets the cookie and redirects to the referer.