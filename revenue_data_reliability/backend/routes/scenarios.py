"""Scenario routes: webhook registration."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from backend.config import settings
from backend.services import scenarios as scen_svc

router = APIRouter()


def _verify_token(request: Request, payload: dict):
    token = (
        request.headers.get("X-Webhook-Token")
        or request.query_params.get("token")
        or (payload.get("webhook_token") if isinstance(payload, dict) else None)
    )
    return token == settings.webhook_token


@router.delete("/api/scenarios/{scenario_id}")
async def delete_scenario(scenario_id: str):
    from backend.services import scenarios as scen_svc

    scen_svc.delete_scenario(scenario_id)
    return JSONResponse({"status": "deleted", "scenario": scenario_id})


@router.post("/api/scenarios/register")
async def register_scenario(request: Request):
    try:
        payload = await request.json()
    except Exception:
        form = await request.form()
        payload = dict(form)
    if not _verify_token(request, payload):
        return JSONResponse({"error": "invalid webhook token"}, status_code=401)
    try:
        scen = scen_svc.register_scenario(payload)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"status": "registered", "scenario": scen["name"]})
