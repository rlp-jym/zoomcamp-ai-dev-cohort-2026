"""In-process APScheduler (SPEC §6).

Runs the two background jobs alongside the FastAPI app process:

* ``controller_verification`` — Controller stale-publication checks every
  N minutes (Phase 2 skeleton; alerting lands in Phase 3).
* ``otel_retention`` — deletes OTEL spans/logs/metrics older than the
  retention window.

The scheduler starts and stops with the FastAPI lifecycle so tests,
docker, and Render deploys all behave the same way.
"""

import logging

from apscheduler.schedulers.background import BackgroundScheduler

_scheduler: BackgroundScheduler | None = None

log = logging.getLogger("scheduler")


def start_scheduler() -> BackgroundScheduler:
    """Create and start the scheduler with all registered jobs (idempotent)."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return _scheduler

    from backend.config import settings
    from backend.teams.controller import run_controller_verification
    from observability.telemetry import run_retention

    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        run_controller_verification,
        "interval",
        minutes=settings.controller_interval_minutes,
        id="controller_verification",
        replace_existing=True,
        max_instances=1,
    )
    _scheduler.add_job(
        run_retention,
        "interval",
        hours=24,
        id="otel_retention",
        replace_existing=True,
        max_instances=1,
    )
    _scheduler.start()
    log.info(
        "Scheduler started: controller every %s min, retention every 24h",
        settings.controller_interval_minutes,
    )
    return _scheduler


def shutdown_scheduler(wait: bool = False) -> None:
    """Stop the scheduler (with the app lifespan)."""
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=wait)
        except Exception:  # pragma: no cover - best-effort stop
            pass
        _scheduler = None
        log.info("Scheduler stopped")


def get_scheduler() -> BackgroundScheduler | None:
    return _scheduler
