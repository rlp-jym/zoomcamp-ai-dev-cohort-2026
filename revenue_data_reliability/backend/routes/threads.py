"""HTMX thread interaction endpoints (in-memory stub)."""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from backend.config import settings
from backend.db.connection import fetch_one
from backend.services import messages, stub_data
from backend.templating import templates

router = APIRouter()


def _current_persona(request: Request):
    pid = request.cookies.get(settings.persona_cookie, "analyst")
    return stub_data.get_persona(pid)


def _anchor_trace_id(anchor_type: str, anchor_id: str):
    """Inherit the trace of the run/exception a thread is attached to."""
    try:
        if anchor_type == "run":
            row = fetch_one(
                "SELECT trace_id FROM runs WHERE run_id = %s", (int(anchor_id),)
            )
            return row["trace_id"] if row else None
        if anchor_type == "exception":
            row = fetch_one(
                "SELECT trace_id FROM exceptions WHERE exception_id = %s",
                (int(anchor_id),),
            )
            return row["trace_id"] if row else None
    except (TypeError, ValueError):
        return None
    return None


@router.post("/threads/{anchor_type}/{anchor_id}/messages")
async def post_message(request: Request, anchor_type: str, anchor_id: str):
    form = await request.form()
    content = (form.get("content") or "").strip()
    persona = _current_persona(request)
    if content:
        messages.post_message(
            anchor_type,
            anchor_id,
            persona,
            content,
            trace_id=_anchor_trace_id(anchor_type, anchor_id),
        )
        try:
            from backend.services import dashboard as _dashboard_svc

            _dashboard_svc.invalidate_dashboard_cache()
        except Exception:
            pass
    msgs = messages.get_messages(anchor_type, anchor_id)
    return templates.TemplateResponse(
        request,
        "partials/thread.html",
        {
            "request": request,
            "anchor_type": anchor_type,
            "anchor_id": anchor_id,
            "messages": msgs,
        },
    )


@router.delete("/threads/{anchor_type}/{anchor_id}")
async def delete_thread(request: Request, anchor_type: str, anchor_id: str):
    messages.delete_discussion_by_anchor(anchor_type, anchor_id)
    return HTMLResponse("")