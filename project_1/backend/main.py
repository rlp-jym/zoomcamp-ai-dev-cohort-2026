"""Application entry point."""

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.config import STATIC_DIR, TEMPLATES_DIR
from backend.routes import pages, personas, threads

# Ensure templates dir exists (no-op if present)
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)


def create_app() -> FastAPI:
    app = FastAPI(title="Revenue Data Reliability Platform")

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    app.include_router(personas.router)
    app.include_router(threads.router)
    app.include_router(pages.router)

    @app.get("/health")
    async def health():
        return JSONResponse({"status": "ok"})

    return app


app = create_app()