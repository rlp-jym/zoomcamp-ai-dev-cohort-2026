"""Dataset routes: registration and deletion."""

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


@router.delete("/api/datasets/{dataset_name}")
@router.delete("/api/scenarios/{dataset_name}")
async def delete_dataset(request: Request, dataset_name: str):
    from fastapi.responses import HTMLResponse

    scen_svc.delete_dataset(dataset_name)
    # Tell the header dataset selector to re-fetch so a deleted dataset does
    # not linger in the dropdown.
    headers = {"HX-Trigger": "datasets-changed"}
    if request.headers.get("HX-Request") == "true":
        # The delete button swaps its table row; return no body so the row
        # disappears instead of being replaced by a JSON blob.
        return HTMLResponse("", headers=headers)
    return JSONResponse(
        {"status": "deleted", "dataset": dataset_name}, headers=headers
    )


@router.post("/api/datasets/register")
@router.post("/api/scenarios/register")
async def register_dataset(request: Request):
    try:
        payload = await request.json()
    except Exception:
        form = await request.form()
        payload = dict(form)
    if not _verify_token(request, payload):
        return JSONResponse({"error": "invalid webhook token"}, status_code=401)
    try:
        dataset = scen_svc.register_dataset(payload)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"status": "registered", "dataset": dataset["name"]})
