"""Application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.config import STATIC_DIR, TEMPLATES_DIR
from backend.db import apply_schema, close_pool, get_connection, init_pool, seed
from backend.routes import debug, pages, personas, scenarios, threads
from backend.services.backfill import trigger_backfill
from backend.services.scheduler import shutdown_scheduler, start_scheduler
from backend.storage import init_duckdb
from opentelemetry.instrumentation.utils import suppress_instrumentation
from observability.telemetry import setup_telemetry, shutdown_telemetry

# Ensure templates dir exists (no-op if present)
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO)
    # Boot-time schema/seed writes are one-off statements that would emit a
    # cloud of single-span traces on every start; keep them out of OTEL.
    with suppress_instrumentation():
        init_pool()
        apply_schema()
        seed()
    # Fail loudly if httpfs is unavailable.
    init_duckdb()

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM scenarios")
                count = cur.fetchone()[0]
        if count == 0:
            trigger_backfill()
        from backend.services import scenarios as scen_svc
        scen_svc.ensure_baseline_registered()
    except Exception as exc:
        logger.error("Backfill check failed: %s", exc)

    # In-process scheduler (SPEC §6): controller verification + OTEL retention.
    start_scheduler()

    yield

    shutdown_scheduler()
    shutdown_telemetry()
    close_pool()


def create_app() -> FastAPI:
    app = FastAPI(title="Revenue Data Reliability Platform", lifespan=lifespan)

    # OTEL instrumentation before the pool opens for business, so FastAPI,
    # psycopg, and boto3 calls are all traced and exported to Postgres.
    setup_telemetry(app)

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    app.include_router(personas.router)
    app.include_router(threads.router)
    app.include_router(pages.router)
    app.include_router(scenarios.router)
    app.include_router(debug.router)

    @app.get("/health")
    async def health():
        return JSONResponse({"status": "ok"})

    return app


app = create_app()
