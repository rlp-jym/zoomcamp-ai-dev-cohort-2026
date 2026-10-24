"""Application entry point."""

import logging
import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from opentelemetry.instrumentation.utils import suppress_instrumentation

from backend.config import STATIC_DIR, TEMPLATES_DIR
from backend.db import (
    apply_schema,
    close_pool,
    ensure_baseline_fixture,
    get_connection,
    init_pool,
    seed,
)
from backend.routes import debug, pages, personas, scenarios, threads
from backend.services.scheduler import shutdown_scheduler, start_scheduler
from backend.storage import init_duckdb
from backend.storage.scenario_cache import ensure_local_scenario, scenario_s3_prefix
from observability.telemetry import setup_telemetry, shutdown_telemetry

# Ensure templates dir exists (no-op if present)
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
STATIC_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger(__name__)


def _warm_scenario_cache():
    """Download the canonical 5-year scenario in the background at boot."""
    try:
        target = ensure_local_scenario(
            "baseline_seed9_y5", scenario_s3_prefix("baseline_seed9_y5")
        )
        logger.info("Scenario cache warm at %s", target)
    except Exception as exc:  # never block or crash app startup
        logger.warning("Scenario cache warmup failed: %s", exc)


def _cache_warmup_enabled() -> bool:
    value = os.getenv("SCENARIO_CACHE_WARMUP", "1").strip().lower()
    return value not in {"0", "false", "no", "off"}


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
                cur.execute("SELECT COUNT(*) FROM datasets")
                count = cur.fetchone()[0]
        if count == 0:
            # Clean slate: boot never registers or generates a dataset. The
            # reviewer must use "Load Dataset" on the Validation page.
            logger.info("No datasets registered; waiting for a reviewer to load one.")
        ensure_baseline_fixture()
        from backend.services import runs as runs_svc
        failed = runs_svc.sweep_stale_runs(0)
        if failed:
            logger.info("Marked %s stale running run(s) as failed.", failed)
    except Exception as exc:
        logger.error("Backfill check failed: %s", exc)

    # In-process scheduler (SPEC §6): controller verification + OTEL retention.
    start_scheduler()

    # Warm the local Parquet cache so the first validation does not pay the
    # S3 download cost.  This is a daemon thread: startup and health checks
    # stay responsive while the ~400 MB fixture downloads.
    if _cache_warmup_enabled():
        threading.Thread(
            target=_warm_scenario_cache,
            name="scenario-cache-warmup",
            daemon=True,
        ).start()

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

    @app.middleware("http")
    async def dataset_cookie_middleware(request, call_next):
        response = await call_next(request)
        dataset = request.query_params.get("dataset") or request.query_params.get("scenario")
        if dataset:
            response.set_cookie("dataset", dataset, max_age=30 * 24 * 3600, path="/")
        if getattr(request.state, "clear_dataset_cookie", False):
            response.delete_cookie("dataset", path="/")
            response.delete_cookie("scenario", path="/")
        return response

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
