"""Page routes rendering templates with stub context."""

from fastapi import APIRouter, Request

from backend.config import settings
from backend.services import messages, stub_data
from backend.templating import templates

router = APIRouter()


def _current_persona(request: Request):
    pid = request.cookies.get(settings.persona_cookie, "analyst")
    return stub_data.get_persona(pid)


def _ctx(request: Request, **extra):
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
        request, "exceptions_list.html", _ctx(request, exceptions=stub_data.EXCEPTIONS)
    )


@router.get("/exceptions/{exc_id}")
async def exception_detail(request: Request, exc_id: int):
    exc = next((e for e in stub_data.EXCEPTIONS if e["id"] == exc_id), stub_data.EXCEPTIONS[0])
    msgs = messages.get_messages("exception", str(exc_id))
    return templates.TemplateResponse(
        request,
        "exception_detail.html",
        _ctx(request, exception=exc, anchor_type="exception", anchor_id=str(exc_id), messages=msgs),
    )


@router.get("/runs")
async def runs_list(request: Request):
    return templates.TemplateResponse(
        request, "runs_list.html", _ctx(request, runs=stub_data.RUNS)
    )


@router.get("/runs/{run_id}")
async def run_detail(request: Request, run_id: int):
    run = dict(stub_data.RUN_DETAIL, id=run_id)
    msgs = messages.get_messages("run", str(run_id))
    if not msgs and run_id != 1:
        msgs = list(messages.get_messages("run", "1"))
    return templates.TemplateResponse(
        request,
        "run_detail.html",
        _ctx(request, run=run, anchor_type="run", anchor_id=str(run_id), messages=msgs),
    )


@router.get("/scenarios")
async def scenarios(request: Request):
    return templates.TemplateResponse(
        request, "scenarios.html", _ctx(request, scenarios=stub_data.SCENARIOS)
    )


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