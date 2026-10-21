"""Page routes rendering templates with real data."""
from __future__ import annotations

import json
import os
import threading
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from backend.config import settings
from backend.db import execute, fetch_one
from backend.db.reset import reset_preserve_baseline
from backend.services import exceptions as exc_svc
from backend.services import messages, stub_data
from backend.services import publications as pub_svc
from backend.services import quarantines as quarantines_svc
from backend.services import runs as runs_svc
from backend.services import scenarios as scen_svc
from backend.services import validations as val_svc
from backend.teams.de import DEAgent
from backend.templating import templates

router = APIRouter()

_reset_lock = threading.Lock()


def _current_persona(request: Request):
    pid = request.cookies.get(settings.persona_cookie, "analyst")
    return stub_data.get_persona(pid)


def _ctx(request, **extra):
    return {"request": request, "persona": _current_persona(request), **extra}


@router.get("/")
async def dashboard(request: Request):
    """§19: real KPIs + charts from the published dataset.

    Reads the precomputed dashboard_cache payload (refreshed by the
    scheduler / manual refresh) so the request never scans S3 — page loads
    stay fast, and a long S3 outage can only delay the refresh job.
    """
    from backend.services import dashboard as dashboard_svc

    data = dashboard_svc.get_dashboard_data_cached()
    return templates.TemplateResponse(request, "dashboard.html", _ctx(request, **data))


@router.post("/dashboard/refresh")
async def dashboard_refresh(request: Request):
    """Recompute the dashboard cache in a background thread (S3 heavy)."""
    import threading

    from backend.services import dashboard as dashboard_svc

    def _job():
        try:
            dashboard_svc.refresh_dashboard_cache()
        except Exception:  # logged inside refresh; keep the server safe
            pass

    threading.Thread(target=_job, daemon=True).start()
    return RedirectResponse(url="/", status_code=303)


@router.get("/exceptions")
async def exceptions_list(request: Request, status: str | None = None):
    return templates.TemplateResponse(
        request,
        "exceptions_list.html",
        _ctx(request,
             exceptions=exc_svc.list_exceptions(status),
             status_filter=status or "open",
             counts=exc_svc.exception_counts(),
             trend=exc_svc.exception_trend()),
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
    if exc["status"] == "resolved":
        raise HTTPException(status_code=400, detail="Exception is already resolved.")

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

    - Updates exception status to 'resolved'.
    - DE agent logs execution to agent_actions.
    - Posts a system message to the exception thread.
    - Redirects back to the exception detail page.
    """
    persona = _current_persona(request)
    if persona["id"] != "manager":
        raise HTTPException(status_code=403, detail="Only the Manager can approve exceptions.")

    exc = exc_svc.get_exception(exc_id)
    if not exc:
        raise HTTPException(status_code=404, detail="Exception not found.")
    if exc["status"] == "resolved":
        raise HTTPException(status_code=400, detail="Exception is already resolved.")

    trace_id = exc.get("trace_id")

    execute(
        "UPDATE exceptions SET status = 'resolved' WHERE exception_id = %s",
        (exc_id,),
    )

    de_agent = DEAgent()
    de_agent.execute_remediation(exc, trace_id)

    messages.post_message(
        "exception",
        str(exc_id),
        stub_data.get_persona("manager"),
        f"Exception #{exc_id} resolved. Remediation approved by Manager and executed by DE.",
        trace_id=trace_id,
        evidence={"resolved": True, "approved_by": "manager"},
    )

    return RedirectResponse(url=f"/exceptions/{exc_id}", status_code=303)


@router.get("/runs")
async def runs_list(request: Request, reset: str | None = None, busy: str | None = None):
    persona = _current_persona(request)
    return templates.TemplateResponse(
        request,
        "runs_list.html",
        _ctx(request, runs=runs_svc.list_runs(), reset_status=reset, busy=busy,
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
                    "scenarios_deleted": summary.scenarios_deleted,
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
    run = runs_svc.get_run(run_id)
    if not run:
        run = {"id": run_id, "scenario": "", "status": "not_found", "started_at": None,
               "finished_at": None, "duration": None, "triggered_by": None, "trace_id": None,
               "validations_total": 0, "validations_failed": 0, "exceptions_created": 0,
               "published": False, "published_at": None, "approved_at": None}
    msgs = messages.get_messages("run", str(run_id))
    validations = val_svc.list_validations(run_id)
    publication = pub_svc.get_publication_for_run(run_id)
    return templates.TemplateResponse(
        request,
        "run_detail.html",
        _ctx(request, run=run, anchor_type="run", anchor_id=str(run_id),
             messages=msgs, validations=validations, publication=publication),
    )


@router.get("/scenarios")
async def scenarios(request: Request):
    src_type = request.query_params.get("src_type")
    src_id = request.query_params.get("src_id")
    return templates.TemplateResponse(
        request, "scenarios.html",
        _ctx(request, scenarios=scen_svc.list_analysis_scenarios(),
             src_type=src_type, src_id=src_id),
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
async def approve_run(request: Request, run_id: int):
    """Manager approves go-live: publication row + published pointer.

    Creates a row in the `publications` table, moves the scenario's
    published pointer to this run, and posts a confirmation to the run
    thread. Only the Manager persona may approve.
    """
    persona = _current_persona(request)
    if persona["id"] != "manager":
        raise HTTPException(status_code=403, detail="Only the Manager can approve go-live.")

    run = runs_svc.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found.")
    if run["status"] != "completed":
        raise HTTPException(status_code=400, detail="Only completed runs can be published.")

    trace_id = run["trace_id"]
    pub = pub_svc.publish_run(run_id, persona["id"], trace_id)

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
    return RedirectResponse(url=f"/runs/{run_id}", status_code=303)


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
    """§20: real agent_actions / approvals / publications, trace filterable."""
    from backend.db.connection import fetch_all

    clause, params = "", ()
    if trace_id:
        clause = " WHERE trace_id = %s"
        params = (trace_id,)
    actions = fetch_all(
        f"""
        SELECT action_id, agent_id, action, anchor_type, anchor_id,
               trace_id, payload, created_at
        FROM agent_actions{clause}
        ORDER BY action_id DESC
        LIMIT 200
        """,
        params,
    )
    approvals = fetch_all(
        f"""
        SELECT approval_id, target_type, target_id, persona_id, decision,
               trace_id, created_at
        FROM approvals{clause}
        ORDER BY approval_id DESC
        LIMIT 100
        """,
        params,
    )
    publications = fetch_all(
        """
        SELECT p.publication_id, p.run_id, p.published_by, p.pointer,
               p.published_at, r.trace_id
        FROM publications p
        LEFT JOIN runs r ON r.run_id = p.run_id
        ORDER BY p.publication_id DESC
        LIMIT 50
        """
    )
    return templates.TemplateResponse(
        request, "audit.html",
        _ctx(request, actions=actions, approvals=approvals,
             publications=publications, trace_id=trace_id),
    )


@router.get("/observability")
async def observability(request: Request, trace_id: str | None = None):
    """Render real OTEL traces from the otel_spans / otel_logs tables."""
    from backend.services import observability as obs_svc

    traces = obs_svc.list_traces()
    selected = trace_id or (traces[0]["trace_id"] if traces else None)
    spans = obs_svc.get_span_tree(selected) if selected else []
    logs = obs_svc.get_trace_logs(selected) if selected else []
    summary = obs_svc.telemetry_summary()
    return templates.TemplateResponse(
        request,
        "observability.html",
        _ctx(
            request,
            traces=traces,
            expanded_trace=selected,
            expanded_spans=spans,
            trace_logs=logs,
            summary=summary,
        ),
    )
