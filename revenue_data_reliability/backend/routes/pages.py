"""Page routes rendering templates with real data."""
from __future__ import annotations

import json
import logging
import os
import threading
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from backend.config import settings
from backend.db import execute, fetch_one
from backend.db.reset import reset_preserve_baseline
from backend.services import audit as audit_svc
from backend.services import exceptions as exc_svc
from backend.services import messages, stub_data
from backend.services import publications as pub_svc
from backend.services import quarantines as quarantines_svc
from backend.services import runs as runs_svc
from backend.services import scenarios as scen_svc
from backend.services import validations as val_svc
from backend.teams.de import DEAgent
from backend.templating import dataset_label, templates

router = APIRouter()
logger = logging.getLogger(__name__)

_reset_lock = threading.Lock()




def _current_persona(request: Request):
    pid = request.cookies.get(settings.persona_cookie, "analyst")
    return stub_data.get_persona(pid)


def _resolve_dataset(request, extra):
    if "dataset" in extra and extra.get("dataset") is not None:
        return extra.get("dataset")
    qp = request.query_params.get("dataset") or request.query_params.get("scenario")
    if qp:
        return qp
    cookie = request.cookies.get("dataset") or request.cookies.get("scenario")
    if cookie:
        try:
            if scen_svc.get_dataset(cookie):
                return cookie
            request.state.clear_dataset_cookie = True
        except Exception:
            pass
    try:
        return runs_svc.default_dataset()
    except Exception:
        return "baseline_run"


def _ctx(request, **extra):
    dataset = _resolve_dataset(request, extra)
    datasets = extra.pop("datasets", None) or extra.pop("scenarios", None)
    if datasets is None:
        try:
            datasets = scen_svc.list_datasets()
        except Exception:
            datasets = []
    active_run_id = extra.pop("active_run_id", None)
    if active_run_id is None:
        try:
            active_run_id = runs_svc.resolve_active_run(dataset)
        except Exception:
            active_run_id = None
    active_run = None
    if active_run_id is not None:
        try:
            active_run = runs_svc.get_run(active_run_id)
        except Exception:
            active_run = None
    base = {
        "request": request,
        "persona": _current_persona(request),
        "dataset": dataset,
        "dataset_name": dataset,
        "scenario": dataset,
        "datasets": datasets,
        "scenarios": datasets,
        "active_run_id": active_run_id,
        "active_run": active_run,
    }
    return {**base, **extra}


@router.get("/")
async def dashboard(request: Request):
    """§19: real KPIs + charts from the published dataset.

    Reads the precomputed dashboard_cache payload (refreshed by the
    scheduler / manual refresh) so the request never scans S3 — page loads
    stay fast, and a long S3 outage can only delay the refresh job.
    """
    from backend.services import dashboard as dashboard_svc

    dataset = _resolve_dataset(request, {})
    active_run_id = runs_svc.resolve_active_run(dataset)
    data = dashboard_svc.get_dashboard_data_cached(dataset)
    data["active_run_id"] = active_run_id
    has_published_data = bool(data.get("published_run"))
    if not has_published_data:
        try:
            has_published_data = pub_svc.get_published_run(dataset) is not None
        except Exception:
            has_published_data = False
    data["has_published_data"] = has_published_data
    data["cache_building"] = bool(data.get("cache_empty") and has_published_data)
    data["dataset_label"] = dataset_label(dataset) or dataset or "—"
    resp = templates.TemplateResponse(request, "dashboard.html", _ctx(request, **data))
    return resp


def _cache_rebuild_html(dataset):
    from urllib.parse import quote

    query = quote(str(dataset or ""), safe="")
    return HTMLResponse(
        '<div class="banner banner-info">Cache rebuild started. This may take '
        "10-15 seconds. "
        f'<span hx-get="/dashboard/status?dataset={query}" hx-trigger="every 2s">'
        "Waiting for data...</span></div>"
    )


@router.post("/dashboard/refresh")
async def dashboard_refresh(request: Request):
    """Kick off a background dashboard rebuild and return immediately."""
    from backend.services import dashboard as dashboard_svc

    dataset = _resolve_dataset(request, {})
    dashboard_svc.start_dashboard_refresh(dataset)
    return _cache_rebuild_html(dataset)


@router.get("/dashboard/status")
async def dashboard_status(request: Request):
    """HTMX poller: refresh the page once the cache rebuild finishes."""
    from urllib.parse import quote

    from backend.services import dashboard as dashboard_svc

    dataset = _resolve_dataset(request, {})
    query = quote(str(dataset or ""), safe="")
    if dashboard_svc.dashboard_cache_status(dataset) == "ready":
        # The publish flow polls this endpoint; land on the dashboard rather
        # than reloading the run page.
        target = f"/?scenario={query}" if query else "/"
        return Response(status_code=200, headers={"HX-Redirect": target})
    return HTMLResponse(
        f'<span hx-get="/dashboard/status?dataset={query}" hx-trigger="every 2s">'
        "Waiting for data...</span>"
    )


@router.get("/exceptions")
async def exceptions_list(request: Request, status: str | None = None, run_id: str | None = None, limit: int = 50, offset: int = 0):
    dataset = _resolve_dataset(request, {})
    active_run_id = runs_svc.resolve_active_run(dataset)
    try:
        run_id_int = int(run_id) if run_id not in (None, "") else None
    except (TypeError, ValueError):
        run_id_int = None
    # Direct ?run_id= links win; otherwise scope to the active run.
    filter_run_id = run_id_int if run_id_int is not None else active_run_id
    status_filter = status or "open"
    if filter_run_id is None and run_id_int is None and active_run_id is None:
        exceptions = []
    else:
        exceptions = exc_svc.list_exceptions(status_filter, limit=limit, offset=offset, run_id=filter_run_id)
    return templates.TemplateResponse(
        request,
        "exceptions_list.html",
        _ctx(request, dataset=dataset,
             exceptions=exceptions,
             status_filter=status_filter,
             counts=exc_svc.exception_counts(filter_run_id),
             limit=limit,
             offset=offset,
             run_id=run_id_int,
             active_run_id=active_run_id,
             filtered_run_id=filter_run_id),
    )


@router.get("/exceptions/{exc_id}")
async def exception_detail(request: Request, exc_id: int):
    exc = exc_svc.get_exception(exc_id)
    if not exc:
        exc = {"id": exc_id, "type": "validation", "severity": "low", "period": None,
               "title": "Not found", "status": "open", "trace_id": None,
               "rule_id": None, "details": None}
    msgs = messages.get_messages("exception", str(exc_id))
    sampled = []
    reconciliation_rows = []
    quarantine_rows = quarantines_svc.list_quarantines_for_exception(exc_id)
    if exc.get("type") == "reconciliation":
        reconciliation_rows = exc_svc.get_reconciliation_rows_for_exception(exc)
    else:
        sampled = exc_svc.get_sampled_failures_for_exception(exc)
    return templates.TemplateResponse(
        request,
        "exception_detail.html",
        _ctx(request, exception=exc, anchor_type="exception", anchor_id=str(exc_id),
             messages=msgs, sampled_failures=sampled,
             reconciliation_rows=reconciliation_rows, quarantines=quarantine_rows),
    )


@router.post("/exceptions/{exc_id}/quarantine")
async def quarantine_exception(request: Request, exc_id: int):
    """DE agent quarantines the affected records for an exception.

    - Inserts one row in the `quarantines` table (reason code + record keys).
    - Logs the bounded write to agent_actions.
    - Posts a message on the exception thread and resolves the exception.
    """
    persona = _current_persona(request)
    if persona["id"] != "de":
        raise HTTPException(status_code=403, detail="Only the DE agent can quarantine records.")

    exc = exc_svc.get_exception(exc_id)
    if not exc:
        raise HTTPException(status_code=404, detail="Exception not found.")
    if exc["status"] in ("resolved", "approved", "dismissed", "rejected"):
        raise HTTPException(status_code=400, detail="Exception is already closed.")

    trace_id = exc.get("trace_id")
    de_agent = DEAgent()
    quarantine_id, count = de_agent.execute_quarantine(exc, trace_id)

    execute(
        "UPDATE exceptions SET status = 'resolved', updated_at = now() WHERE exception_id = %s",
        (exc_id,),
    )

    return RedirectResponse(url=f"/exceptions/{exc_id}", status_code=303)


@router.post("/exceptions/{exc_id}/approve")
async def approve_exception(request: Request, exc_id: int):
    """Manager approves remediation for an exception.

    - Transitions the exception to 'approved'.
    - DE agent executes the quarantine for the approved remediation.
    - Transitions the exception to terminal 'resolved'.
    """
    persona = _current_persona(request)
    if persona["id"] != "manager":
        raise HTTPException(status_code=403, detail="Only the Manager can approve exceptions.")

    exc = exc_svc.get_exception(exc_id)
    if not exc:
        raise HTTPException(status_code=404, detail="Exception not found.")
    if exc["status"] in ("resolved", "approved", "dismissed", "rejected"):
        raise HTTPException(status_code=400, detail="Exception is already closed.")

    trace_id = exc.get("trace_id")

    execute(
        "UPDATE exceptions SET status = 'approved', updated_at = now() WHERE exception_id = %s",
        (exc_id,),
    )

    de_agent = DEAgent()
    de_agent.execute_quarantine(exc, trace_id)

    execute(
        "UPDATE exceptions SET status = 'resolved', updated_at = now() WHERE exception_id = %s",
        (exc_id,),
    )
    execute(
        "INSERT INTO agent_actions "
        "(agent_id, action, anchor_type, anchor_id, trace_id, payload) "
        "VALUES (%s, %s, 'exception', %s, %s, %s)",
        (
            "manager",
            "Exception Approved",
            str(exc_id),
            trace_id,
            json.dumps(
                {
                    "exception_id": exc_id,
                    "status": "resolved",
                    "rule_id": exc.get("rule_id"),
                }
            ),
        ),
    )

    messages.post_message(
        "exception",
        str(exc_id),
        stub_data.get_persona("manager"),
        (
            f"Exception #{exc_id} approved by Manager; DE executed the quarantine. "
            "Status: resolved."
        ),
        trace_id=trace_id,
        evidence={
            "approved": True,
            "resolved": True,
            "approved_by": "manager",
            "status": "resolved",
        },
    )

    return RedirectResponse(url=f"/exceptions/{exc_id}", status_code=303)


@router.post("/exceptions/dismiss-all")
async def dismiss_all_exceptions(request: Request):
    """Manager closes every open issue for the current filter in one action."""
    persona = _current_persona(request)
    if persona["id"] != "manager":
        raise HTTPException(status_code=403, detail="Only the Manager can dismiss exceptions.")

    form = await request.form()
    raw = form.get("run_id")
    try:
        run_id = int(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        run_id = None

    dismissed = exc_svc.dismiss_all(run_id)
    execute(
        "INSERT INTO agent_actions "
        "(agent_id, action, anchor_type, anchor_id, trace_id, payload) "
        "VALUES (%s, %s, 'run', %s, %s, %s)",
        (
            "manager",
            "Exceptions Dismissed",
            str(run_id) if run_id is not None else "all",
            None,
            json.dumps({"dismissed": dismissed, "run_id": run_id}),
        ),
    )
    target = "/exceptions?status=open"
    if run_id is not None:
        target += f"&run_id={run_id}"
    return RedirectResponse(url=target, status_code=303)


@router.post("/exceptions/{exc_id}/dismiss")
async def dismiss_exception(request: Request, exc_id: int):
    """Manager dismisses an open issue as a false positive."""
    persona = _current_persona(request)
    if persona["id"] != "manager":
        raise HTTPException(status_code=403, detail="Only the Manager can dismiss exceptions.")

    exc = exc_svc.get_exception(exc_id)
    if not exc:
        raise HTTPException(status_code=404, detail="Exception not found.")
    if exc["status"] not in ("open", "awaiting_approval"):
        raise HTTPException(
            status_code=400,
            detail="Only open or awaiting-approval exceptions can be dismissed.",
        )

    execute(
        "UPDATE exceptions SET status = 'dismissed', updated_at = now() WHERE exception_id = %s",
        (exc_id,),
    )
    execute(
        "INSERT INTO agent_actions "
        "(agent_id, action, anchor_type, anchor_id, trace_id, payload) "
        "VALUES (%s, %s, 'exception', %s, %s, %s)",
        (
            "manager",
            "Exception Dismissed",
            str(exc_id),
            exc.get("trace_id"),
            json.dumps(
                {
                    "exception_id": exc_id,
                    "status": "dismissed",
                    "rule_id": exc.get("rule_id"),
                }
            ),
        ),
    )
    messages.post_message(
        "exception",
        str(exc_id),
        persona,
        "Remediation dismissed as a false positive. Status: dismissed.",
        trace_id=exc.get("trace_id"),
        evidence={"dismissed": True, "dismissed_by": "manager"},
    )
    return RedirectResponse(url=f"/exceptions/{exc_id}", status_code=303)


@router.post("/exceptions/{exc_id}/request-fix")
async def request_exception_fix(request: Request, exc_id: int):
    """Manager/DE asks the DE Agent to propose a remediation for one issue.

    The pipeline no longer auto-proposes remediation; this is the explicit
    human trigger. The DE Agent updates the exception to awaiting_approval.
    """
    persona = _current_persona(request)
    if persona["id"] not in ("manager", "de"):
        raise HTTPException(
            status_code=403,
            detail="Only the Manager or DE Agent can request remediation.",
        )

    exc = exc_svc.get_exception(exc_id)
    if not exc:
        raise HTTPException(status_code=404, detail="Exception not found.")
    if exc["status"] not in ("open", "in_discussion"):
        raise HTTPException(
            status_code=400,
            detail="Remediation can only be requested for open or in-discussion exceptions.",
        )

    de_agent = DEAgent()
    de_agent.propose_remediation(exc, exc.get("trace_id"))

    return RedirectResponse(url=f"/exceptions/{exc_id}", status_code=303)


@router.get("/runs")
async def runs_list(request: Request, reset: str | None = None, busy: str | None = None):
    persona = _current_persona(request)
    from backend.services import runs as runs_svc2

    runs_svc2.sweep_stale_runs(10)
    dataset = _resolve_dataset(request, {})
    for r in runs_svc2.list_runs(dataset):
        if r.get("status") == "failed":
            runs_svc2.reconcile_failed_run(r["id"])
    from backend.services import dataset_scale
    from backend.services import scenarios as scen_svc

    datasets = dataset_scale.attach_scale_info(scen_svc.list_datasets())
    runs = runs_svc.list_runs(dataset)
    from backend.templating import scenario_label

    pre_generated = []
    for seed in scen_svc.available_seeds():
        entry = scen_svc.pre_generated_dataset(seed)
        if entry:
            pre_generated.append(
                {"seed": seed, "label": scenario_label(entry["name"])}
            )
    return templates.TemplateResponse(
        request,
        "runs_list.html",
        _ctx(request, dataset=dataset,
             runs=runs,
             latest_run_id=runs_svc2.resolve_active_run(dataset),
             datasets=datasets,
             pre_generated=pre_generated,
             reset_status=reset, busy=busy,
             allow_reset=(
                 os.getenv("ALLOW_IN_APP_RESET", "1") == "1"
                 and persona["id"] == "manager"
             )),
    )


@router.post("/runs/reset")
async def reset_runs(request: Request):
    """Reset non-baseline demo data (Manager-only, env-gated).

    Preserves personas, rules, and the baseline fixture. Truncates the
    ephemeral tables and deletes non-baseline runs/publications/scenarios.
    """
    if os.getenv("ALLOW_IN_APP_RESET", "1") != "1":
        raise HTTPException(status_code=403, detail="In-app reset disabled.")

    form = await request.form()
    confirm = (form.get("confirm") or "").strip()
    if confirm != "RESET":
        raise HTTPException(status_code=400, detail="Type RESET to confirm.")

    persona = _current_persona(request)
    if persona["id"] != "manager":
        raise HTTPException(status_code=403, detail="Only the Manager can reset data.")

    # Guard against truncating under a live pipeline: only a *recent* running
    # run blocks the reset. Older 'running' rows are orphans (crashed
    # pipelines) and are cleared by the reset itself.
    running = fetch_one(
        "SELECT run_id FROM runs WHERE status='running' "
        "AND started_at > now() - interval '10 minutes' LIMIT 1"
    )
    if running:
        raise HTTPException(status_code=409, detail="Cannot reset while a run is running.")

    with _reset_lock:
        summary = reset_preserve_baseline()

    trace_id = uuid.uuid4().hex
    execute(
        "INSERT INTO agent_actions (agent_id, action, anchor_type, anchor_id, trace_id, payload, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, now())",
        (
            "orchestrator",
            "reset_preserve_baseline",
            "system",
            "reset",
            trace_id,
            json.dumps(
                {
                    "runs_deleted": summary.runs_deleted,
                    "datasets_deleted": summary.datasets_deleted,
                    "publications_deleted": summary.publications_deleted,
                }
            ),
        ),
    )

    try:
        from backend.services import dashboard as dashboard_svc

        execute("DELETE FROM dashboard_cache")
        dashboard_svc.invalidate_dashboard_cache()
        threading.Thread(
            target=dashboard_svc.refresh_dashboard_cache, daemon=True
        ).start()
    except Exception:
        pass

    return RedirectResponse(url="/runs?reset=ok", status_code=303)


@router.get("/runs/{run_id}")
async def run_detail(request: Request, run_id: int):
    from backend.services import runs as runs_svc2

    runs_svc2.reconcile_failed_run(run_id)
    run = runs_svc.get_run(run_id)
    if not run:
        run = {"id": run_id, "dataset": "", "scenario": "", "status": "not_found", "started_at": None,
               "finished_at": None, "duration": None, "triggered_by": None, "trace_id": None,
               "validations_total": 0, "validations_failed": 0, "exceptions_created": 0,
               "published": False, "published_at": None, "approved_at": None}
    dataset = run.get("dataset") or run.get("scenario") if isinstance(run, dict) else None
    if not dataset:
        dataset = _resolve_dataset(request, {})
    msgs = messages.get_messages("run", str(run_id))
    validations = val_svc.list_validations(run_id)
    publication = pub_svc.get_publication_for_run(run_id)
    issue_counts = exc_svc.run_issue_counts(run_id)
    template = (
        "partials/run_detail_body.html"
        if request.headers.get("HX-Request") == "true"
        else "run_detail.html"
    )
    return templates.TemplateResponse(
        request,
        template,
        _ctx(request, dataset=dataset, run=run, anchor_type="run", anchor_id=str(run_id),
             messages=msgs, validations=validations, publication=publication,
             issue_counts=issue_counts),
    )


@router.get("/scenarios")
async def scenarios(request: Request):
    src_type = request.query_params.get("src_type")
    src_id = request.query_params.get("src_id")
    return templates.TemplateResponse(
        request, "scenarios.html",
        _ctx(request, analysis_scenarios=scen_svc.list_analysis_scenarios(),
             hide_dataset_selector=True, src_type=src_type, src_id=src_id),
    )


@router.post("/scenarios/create")
async def create_analysis_scenario(request: Request):
    form = await request.form()
    title = form.get("title")
    outcome = form.get("outcome")
    assessment = form.get("assessment")
    baseline_run = form.get("baseline_run") or "baseline_run"
    src_type = None
    src_id = None
    combined = form.get("source_discussion")
    if combined:
        parts = str(combined).split(":", 1)
        if len(parts) == 2:
            src_type, src_id = parts[0], parts[1]
        elif parts and parts[0]:
            src_type, src_id = "analysis", parts[0]
    if not src_type:
        src_type = form.get("source_anchor_type")
    if not src_id:
        src_id = form.get("source_anchor_id")
    sid = scen_svc.create_analysis_scenario(
        title, outcome, assessment, baseline_run,
        source_anchor_type=src_type, source_anchor_id=src_id,
    )
    from_date = form.get("from_date")
    to_date = form.get("to_date")
    if src_type and src_id and (from_date or to_date):
        scen_svc.import_thread_messages(sid, src_type, src_id, from_date or None, to_date or None)
    return RedirectResponse(url=f"/scenarios/{sid}", status_code=303)


@router.post("/scenarios/{scenario_id}/delete")
async def delete_analysis_scenario(request: Request, scenario_id: int):
    scen_svc.delete_analysis_scenario(scenario_id)
    return RedirectResponse(url="/scenarios", status_code=303)


@router.post("/scenarios/{scenario_id}/import")
async def import_scenario_thread(request: Request, scenario_id: int):
    form = await request.form()
    combined = form.get("source_discussion")
    src_type = None
    src_id = None
    if combined:
        parts = str(combined).split(":", 1)
        if len(parts) == 2:
            src_type, src_id = parts[0], parts[1]
        elif parts and parts[0]:
            src_type, src_id = "analysis", parts[0]
    if not src_type:
        src_type = form.get("source_anchor_type")
    if not src_id:
        src_id = form.get("source_anchor_id")
    from_date = form.get("from_date") or None
    to_date = form.get("to_date") or None
    count = 0
    if src_type and src_id:
        count = scen_svc.import_thread_messages(
            scenario_id, src_type, src_id, from_date, to_date
        )
    return RedirectResponse(url=f"/scenarios/{scenario_id}?imported={count}", status_code=303)


@router.get("/scenarios/{scenario_id}")
async def scenario_detail(request: Request, scenario_id: int):
    s = scen_svc.get_analysis_scenario(scenario_id)
    if not s:
        return templates.TemplateResponse(
            request, "scenario_detail.html", _ctx(request, scenario=None, messages=[], source_messages=[], imported=None)
        )
    msgs = messages.get_messages("analysis", str(scenario_id))
    source_msgs = scen_svc.get_source_messages(s)
    imported = request.query_params.get("imported")
    return templates.TemplateResponse(
        request, "scenario_detail.html",
        _ctx(request, scenario=s, messages=msgs, source_messages=source_msgs, imported=imported),
    )


@router.post("/runs/{run_id}/approve")
@router.post("/runs/{run_id}/publish")
async def approve_run(request: Request, run_id: int):
    """Manager approves go-live: publication row + published pointer.

    Blocked while open/awaiting issues remain. After publishing, the
    dataset dashboard cache is invalidated and refreshed synchronously.
    Only the Manager persona may approve.
    """
    persona = _current_persona(request)
    if persona["id"] != "manager":
        raise HTTPException(status_code=403, detail="Only the Manager can approve go-live.")

    run = runs_svc.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found.")
    if run["status"] != "completed":
        raise HTTPException(status_code=400, detail="Only completed runs can be published.")

    issue_counts = exc_svc.run_issue_counts(run_id)
    if issue_counts["open"] > 0:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Cannot publish: {issue_counts['open']} open data issues remain. "
                "Resolve or Dismiss them in the Data Issues page first."
            ),
        )

    trace_id = run["trace_id"]
    pub = pub_svc.publish_run(run_id, persona["id"], trace_id)

    from backend.services import dashboard as dashboard_svc

    dataset_name = run.get("dataset") or run.get("scenario")
    if dataset_name:
        dashboard_svc.invalidate_dashboard_cache(dataset_name)
        dashboard_svc.start_dashboard_refresh(dataset_name)

    if pub["created"]:
        content = (
            f"Go-Live approved by Manager: run #{run_id} is now the published "
            f"run for scenario {run['scenario']} "
            f"(publication #{pub['publication_id']}, pointer `{pub['pointer']}`)."
        )
    else:
        content = (
            f"Run #{run_id} was already published on {pub['published_at']} "
            f"(publication #{pub['publication_id']})."
        )
    messages.post_message(
        "run",
        str(run_id),
        persona,
        content,
        trace_id=trace_id,
        evidence={
            "publication_id": pub["publication_id"],
            "pointer": pub["pointer"],
            "published_by": persona["id"],
        },
    )
    target = f"/runs/{run_id}"
    if request.headers.get("HX-Request") == "true":
        # Return the polling fragment; the page reloads once the cache is ready.
        return _cache_rebuild_html(dataset_name or run.get("scenario"))
    return RedirectResponse(url=target, status_code=303)


@router.post("/runs/{run_id}/reject")
async def reject_run(request: Request, run_id: int):
    persona = _current_persona(request)
    run = runs_svc.get_run(run_id)
    trace_id = run["trace_id"] if run else None
    runs_svc.reject_run(run_id, persona["id"], trace_id)
    messages.post_message(
        "run",
        str(run_id),
        persona,
        "Rejected this run.",
        trace_id=trace_id,
    )
    return RedirectResponse(url=f"/runs/{run_id}", status_code=303)


@router.get("/audit")
async def audit(request: Request, trace_id: str | None = None):
    """Unified chronological ledger of approvals, publications, and actions."""
    from backend.db.connection import fetch_all

    clause, params = "", ()
    if trace_id:
        clause = " WHERE trace_id = %s"
        params = (trace_id,)
    pub_clause, pub_params = "", ()
    if trace_id:
        pub_clause = " WHERE r.trace_id = %s"
        pub_params = (trace_id,)

    actions = fetch_all(
        f"""
        SELECT action_id, agent_id, action, anchor_type, anchor_id,
               trace_id, payload, created_at
        FROM agent_actions{clause}
        ORDER BY created_at DESC NULLS LAST
        LIMIT 200
        """,
        params,
    )
    approvals = fetch_all(
        f"""
        SELECT approval_id, target_type, target_id, persona_id, decision,
               comment, trace_id, created_at
        FROM approvals{clause}
        ORDER BY created_at DESC NULLS LAST
        LIMIT 100
        """,
        params,
    )
    publications = fetch_all(
        f"""
        SELECT p.publication_id, p.run_id, p.published_by, p.pointer,
               p.published_at, r.trace_id
        FROM publications p
        LEFT JOIN runs r ON r.run_id = p.run_id{pub_clause}
        ORDER BY p.published_at DESC NULLS LAST
        LIMIT 50
        """,
        pub_params,
    )
    message_clause = " WHERE m.trace_id = %s" if trace_id else ""
    message_params = (trace_id,) if trace_id else ()
    message_rows = fetch_all(
        f"""
        SELECT m.message_id, m.persona_id, m.content, m.trace_id, m.created_at,
               d.anchor_type, d.anchor_id
        FROM messages m
        JOIN discussions d ON d.discussion_id = m.discussion_id
        {message_clause}
        ORDER BY m.created_at DESC NULLS LAST
        LIMIT 200
        """,
        message_params,
    )

    events = []
    for row in actions:
        events.append(
            {
                "timestamp": audit_svc.format_timestamp(row["created_at"]),
                "sort": str(row["created_at"] or ""),
                "actor": row["agent_id"],
                "action": audit_svc.action_label(row["action"]),
                "target": audit_svc.target_label(
                    row["anchor_type"], row["anchor_id"]
                ),
                "details": audit_svc.format_payload(row["payload"]),
                "trace_id": row["trace_id"],
            }
        )
    for row in approvals:
        events.append(
            {
                "timestamp": audit_svc.format_timestamp(row["created_at"]),
                "sort": str(row["created_at"] or ""),
                "actor": row["persona_id"],
                "action": audit_svc.approval_action(
                    row["decision"], row["target_type"]
                ),
                "target": audit_svc.target_label(
                    row["target_type"], row["target_id"]
                ),
                "details": audit_svc.format_payload(
                    {"comment": row["comment"]} if row["comment"] else None
                ),
                "trace_id": row["trace_id"],
            }
        )
    for row in publications:
        events.append(
            {
                "timestamp": audit_svc.format_timestamp(row["published_at"]),
                "sort": str(row["published_at"] or ""),
                "actor": row["published_by"],
                "action": "Published Go-Live",
                "target": audit_svc.target_label("run", row["run_id"]),
                "details": audit_svc.format_payload(
                    {"pointer": row["pointer"]} if row["pointer"] else None
                ),
                "trace_id": row["trace_id"],
            }
        )
    for row in message_rows:
        events.append(
            {
                "timestamp": audit_svc.format_timestamp(row["created_at"]),
                "sort": str(row["created_at"] or ""),
                "actor": row["persona_id"],
                "action": "Message Posted",
                "target": audit_svc.target_label(
                    row["anchor_type"], row["anchor_id"]
                ),
                "details": audit_svc.format_message(row["content"]),
                "trace_id": row["trace_id"],
            }
        )
    events.sort(key=lambda event: event["sort"], reverse=True)

    return templates.TemplateResponse(
        request,
        "audit.html",
        _ctx(request, events=events, trace_id=trace_id),
    )


@router.get("/observability")
async def observability(request: Request, trace_id: str | None = None):
    """Render real OTEL traces from the otel_spans / otel_logs tables."""
    from backend.services import observability as obs_svc

    traces = obs_svc.list_traces()
    selected = trace_id or (traces[0]["trace_id"] if traces else None)
    selected_name = obs_svc.get_trace_name(selected) if selected else "Unknown"
    spans = obs_svc.get_span_tree(selected) if selected else []
    logs = obs_svc.get_trace_logs(selected) if selected else []
    summary = obs_svc.telemetry_summary()
    latency = obs_svc.latency_series()
    services = obs_svc.spans_by_service()
    return templates.TemplateResponse(
        request,
        "observability.html",
        _ctx(
            request,
            traces=traces,
            expanded_trace=selected,
            expanded_trace_name=selected_name,
            expanded_spans=spans,
            trace_logs=logs,
            summary=summary,
            latency=latency,
            services=services,
        ),
    )


# ---------------------------------------------------------------------------
# Validation page enhancements: generate data + trigger validation runs
# ---------------------------------------------------------------------------

async def _read_payload(request):
    try:
        data = await request.json()
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    try:
        form = await request.form()
        return dict(form)
    except Exception:
        return {}


def _bad_request(request: Request, message: str):
    accept = request.headers.get("accept", "")
    if "application/json" in accept:
        return JSONResponse({"status": "error", "message": message}, status_code=400)
    return HTMLResponse(f'<div class="banner banner-error">{message}</div>', status_code=400)


@router.post("/api/generate-dataset")
@router.post("/api/generate-scenario")
async def generate_dataset(request: Request):
    persona = _current_persona(request)
    if persona["id"] != "analyst":
        raise HTTPException(status_code=403, detail="Only the Analyst can generate datasets.")

    payload = await _read_payload(request)
    try:
        seed = int(payload.get("seed", 101))
    except (TypeError, ValueError):
        seeds = ", ".join(str(value) for value in scen_svc.available_seeds())
        return _bad_request(
            request,
            f"Seed must be a whole number. Available seeds: {seeds}.",
        )

    pre_generated = scen_svc.pre_generated_dataset(seed)
    if pre_generated is None:
        seeds = ", ".join(str(value) for value in scen_svc.available_seeds())
        return _bad_request(
            request,
            f"Seed {seed} has not been pre-generated. Available seeds: {seeds}.",
        )

    # Registration only: data/generate.py runs offline and the Parquet files
    # already live under the dataset's s3_prefix. Never generate in-process.
    try:
        dataset = scen_svc.register_dataset(pre_generated)
        try:
            trace_id = runs_svc.resolve_active_run(dataset["name"])
        except Exception:
            trace_id = None
        execute(
            "INSERT INTO agent_actions "
            "(agent_id, action, anchor_type, anchor_id, trace_id, payload) "
            "VALUES (%s, %s, 'dataset', %s, %s, %s)",
            (
                "analyst",
                "Dataset Loaded",
                dataset["name"],
                trace_id,
                json.dumps(
                    {
                        "seed": seed,
                        "dataset": dataset["name"],
                        "s3_prefix": dataset["s3_prefix"],
                    }
                ),
            ),
        )
        msg = (
            f"Dataset {dataset['name']} is ready "
            f"({dataset['s3_prefix']})."
        )
        accept = request.headers.get("accept", "")
        if "application/json" in accept:
            return JSONResponse(
                {
                    "status": "ready",
                    "message": msg,
                    "dataset": dataset["name"],
                    "seed": seed,
                    "s3_prefix": dataset["s3_prefix"],
                }
            )
        return HTMLResponse(f'<div class="banner banner-ok">{msg}</div>')
    except Exception as exc:
        err_msg = f"Failed to register dataset: {exc}"
        accept = request.headers.get("accept", "")
        if "application/json" in accept:
            return JSONResponse({"status": "error", "message": err_msg}, status_code=500)
        return HTMLResponse(f'<div class="banner banner-error">{err_msg}</div>', status_code=500)


def _trigger_validation(request: Request, dataset_name: str):
    import threading
    import uuid
    from datetime import datetime

    from backend.db.connection import fetch_one
    from backend.services import orchestrator as orch_svc
    from backend.services import runs as runs_svc

    running = fetch_one(
        "SELECT run_id FROM runs WHERE status='running' "
        "AND started_at > now() - interval '10 minutes' LIMIT 1"
    )
    if running:
        return None, "A pipeline is already running. Wait for it to finish."

    trace_id = uuid.uuid4().hex
    run_id = runs_svc.create_run(dataset_name, "analyst", trace_id)

    import logging

    _log = logging.getLogger(__name__)

    def _job():
        _log.info("Background pipeline thread started for run %s", run_id)
        try:
            orch_svc.run_pipeline(run_id)
            _log.info("Background pipeline thread finished for run %s", run_id)
        except Exception as exc:
            _log.exception("Background pipeline thread failed for run %s: %s", run_id, exc)
            try:
                runs_svc.update_run(run_id, status="failed", finished_at=datetime.utcnow(), error_message=str(exc))
            except Exception:
                pass

    threading.Thread(target=_job, daemon=True).start()
    return run_id, None


@router.post("/runs")
@router.post("/runs/validate")
@router.post("/runs/run")
@router.post("/runs/trigger")
@router.post("/api/runs")
@router.post("/api/run-pipeline")
@router.post("/api/validate")
@router.post("/api/trigger-validation")
async def run_validation(request: Request):
    payload = await _read_payload(request)
    dataset_name = (
        payload.get("dataset")
        or payload.get("dataset_name")
        or payload.get("scenario")
        or payload.get("scenario_name")
        or payload.get("scenario_id")
        or payload.get("name")
    )
    if not dataset_name:
        dataset_name = _resolve_dataset(request, {})
    if not dataset_name:
        dataset_name = "baseline_run"

    run_id, err = _trigger_validation(request, str(dataset_name))
    accept = request.headers.get("accept", "")
    if err:
        if "application/json" in accept:
            return JSONResponse({"status": "busy", "message": err}, status_code=409)
        return HTMLResponse(
            f'<tr><td colspan="6" class="banner banner-error">{err}</td></tr>',
            status_code=409,
        )

    from backend.services import runs as runs_svc

    run = runs_svc.get_run(run_id) or {
        "id": run_id,
        "dataset": str(dataset_name),
        "scenario": str(dataset_name),
        "status": "running",
        "current_stage": "Queued",
        "progress_percent": 0,
        "started_at": None,
        "duration_seconds": None,
    }
    if "application/json" in accept:
        return JSONResponse(
            {
                "status": run.get("status"),
                "run_id": run_id,
                "dataset": dataset_name,
                "scenario": dataset_name,
                "poll_url": f"/runs/{run_id}/status",
            }
        )
    return templates.TemplateResponse(
        request, "partials/run_row.html", {"run": run, "initial": True}
    )


@router.get("/runs/{run_id}/status")
async def run_status_partial(request: Request, run_id: int):
    from backend.services import runs as runs_svc

    run = runs_svc.get_run(run_id)
    if not run:
        run = {
            "id": run_id,
            "dataset": "—",
            "scenario": "—",
            "status": "unknown",
            "current_stage": "Unknown",
            "progress_percent": 0,
            "started_at": None,
            "duration_seconds": None,
        }
    elif run.get("status") in ("completed", "failed", "rejected"):
        run["progress_percent"] = 100
    return templates.TemplateResponse(
        request, "partials/run_row.html", {"run": run, "poll_result": True}
    )


@router.delete("/runs/{run_id}")
async def delete_run_endpoint(request: Request, run_id: int):
    from backend.services import runs as runs_svc

    runs_svc.delete_run(run_id)
    return HTMLResponse("")


@router.delete("/api/discussions/{discussion_id}")
async def delete_discussion_endpoint(request: Request, discussion_id: int):
    from backend.services import messages as msg_svc

    msg_svc.delete_discussion(discussion_id)
    return HTMLResponse("")


@router.delete("/api/messages/{message_id}")
async def delete_message_endpoint(request: Request, message_id: int):
    from backend.services import messages as msg_svc

    msg_svc.delete_message(message_id)
    return HTMLResponse("")


@router.get("/api/datasets")
async def datasets_partial(request: Request):
    from backend.services import dataset_scale
    from backend.services import scenarios as scen_svc

    datasets = dataset_scale.attach_scale_info(scen_svc.list_datasets())
    return templates.TemplateResponse(
        request, "partials/datasets_table.html", _ctx(request, datasets=datasets)
    )
