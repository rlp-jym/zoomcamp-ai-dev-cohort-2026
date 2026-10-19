"""Persona selection route (cookie-based, no auth)."""

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from backend.config import settings
from backend.services import stub_data

router = APIRouter()


@router.post("/persona")
async def set_persona(request: Request):
    form = await request.form()
    persona_id = form.get("persona_id") or "analyst"
    if not stub_data.get_persona(persona_id):
        persona_id = "analyst"
    referer = request.headers.get("referer") or "/"
    response = RedirectResponse(url=referer, status_code=303)
    response.set_cookie(
        key=settings.persona_cookie,
        value=persona_id,
        httponly=True,
        samesite="lax",
    )
    return response