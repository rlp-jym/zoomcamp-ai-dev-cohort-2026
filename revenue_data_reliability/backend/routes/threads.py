"""HTMX thread interaction endpoints (in-memory stub)."""

from fastapi import APIRouter, Request

from backend.config import settings
from backend.services import messages, stub_data
from backend.templating import templates

router = APIRouter()


def _current_persona(request: Request):
    pid = request.cookies.get(settings.persona_cookie, "analyst")
    return stub_data.get_persona(pid)


@router.post("/threads/{anchor_type}/{anchor_id}/messages")
async def post_message(request: Request, anchor_type: str, anchor_id: str):
    form = await request.form()
    content = (form.get("content") or "").strip()
    persona = _current_persona(request)
    if content:
        messages.post_message(anchor_type, anchor_id, persona, content)
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