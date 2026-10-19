"""Page routes rendering templates with real data."""

import json
import uuid
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from fastapi import HTTPException

from backend.config import settings
from backend.db.connection import execute, fetch_one
from backend.services import exceptions as exc_svc
from backend.services import messages
from backend.services import runs as runs_svc
from backend.services import scenarios as scen_svc
from backend.services import stub_data
from backend.services import validations as val_svc
from backend.templating import templates
from backend.teams.de import DEAgent

router = APIRouter()


def _current_persona(request: Request):
    pid = request.cookies.get(settings.persona_cookie, "analyst")
    return stub_data.get_persona(pid)


def _ctx(request, **extra):
    return {"request": request, "persona": _current_persona(request), **extra}


@router.get("/")
async def dashboard(request: Request):
    kpis = []
    for k in stub_data.KPIS:
        item = dict(k)
        item["messages"] = messages.get_messages("analysis", k["thread_id"])
        kpis.append(item)
    return templates.TemplateResponse(request, "dashboard.html", _ctx(request, kpis=kpis))


@router.get("/exceptions")
async def exceptions_list(request: Request):
    return templates.TemplateResponse(
        request, "exceptions_list.html", _ctx(request, exceptions=exc_svc.list_exceptions())
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
    if exc.get("type") == "reconciliation":
        reconciliation_rows = exc_svc.get_reconciliation_rows_for_exception(exc)
    else:
        sampled = exc_svc.get_sampled_failures_for_exception(exc)
    return templates.TemplateResponse(
        request,
        "exception_detail.html",
        _ctx(request, exception=exc, anchor_type="exception", anchor_id=str(exc_id),
             messages=msgs, sampled_failures=sampled,
             reconciliation_rows=reconciliation_rows),
    )


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

    # Update exception status to resolved
    execute(
        "UPDATE exceptions SET status = 'resolved' WHERE exception_id = %s",
        (exc_id,),
    )

    # DE agent logs execution (no actual data deletion/quarantine yet)
    de_agent = DEAgent()
    de_agent.execute_remediation(exc, trace_id)

    # Post system message to the thread
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
async def runs_list(request: Request):
    return templates.TemplateResponse(
        request, "runs_list.html", _ctx(request, runs=runs_svc.list_runs())
    )


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
    return templates.TemplateResponse(
        request,
        "run_detail.html",
        _ctx(request, run=run, anchor_type="run", anchor_id=str(run_id),
             messages=msgs, validations=validations),
    )


@router.get("/scenarios")
async def scenarios(request: Request):
    scen_svc.ensure_baseline_registered()
    return templates.TemplateResponse(
        request, "scenarios.html", _ctx(request, scenarios=scen_svc.list_scenarios())
    )


@router.post("/scenarios/{name}/run")
async def run_scenario(request: Request, name: str):
    scen_svc.ensure_baseline_registered()
    persona = _current_persona(request)
    trace_id = uuid.uuid4().hex
    run_id = runs_svc.create_run(name, persona["id"], trace_id)
    from backend.services import orchestrator

    orchestrator.run_pipeline(run_id)
    return RedirectResponse(url=f"/runs/{run_id}", status_code=303)


@router.post("/runs/{run_id}/approve")
async def approve_run(request: Request, run_id: int):
    persona = _current_persona(request)
    run = runs_svc.get_run(run_id)
    trace_id = run["trace_id"] if run else None
    runs_svc.approve_run(run_id, persona["id"], trace_id)
    messages.post_message(
        "run",
        str(run_id),
        persona if persona["id"] == "manager" else stub_data.get_persona("manager"),
        "Approved go-live for this run.",
        trace_id=trace_id,
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
async def audit(request: Request):
    return templates.TemplateResponse(
        request, "audit.html", _ctx(request, rows=stub_data.AUDIT_ROWS)
    )


@router.get("/observability")
async def observability(request: Request):
    return templates.TemplateResponse(
        request,
        "observability.html",
        _ctx(
            request,
            traces=stub_data.TRACES,
            expanded_trace=stub_data.EXPANDED_TRACE,
            expanded_spans=stub_data.EXPANDED_SPANS,
        ),
    )
