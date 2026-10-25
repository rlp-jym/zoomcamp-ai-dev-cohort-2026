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
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler

_scheduler: BackgroundScheduler | None = None

log = logging.getLogger("scheduler")


def _warm_published_dashboard() -> None:
    """Warm the dashboard cache for the published dataset, if there is one.

    Datasets are immutable fixtures and publish is the only event that changes
    the numbers, so boot must not scan Parquet when nothing is published.
    """
    from backend.services import publications as pub_svc
    from backend.services import runs as runs_svc
    from backend.services.dashboard import refresh_dashboard_cache

    try:
        dataset = runs_svc.default_dataset()
    except Exception as exc:
        log.warning("Dashboard warm-up skipped: cannot resolve dataset (%s)", exc)
        return
    if not dataset:
        log.info("Dashboard warm-up skipped: no dataset available.")
        return
    try:
        published = pub_svc.get_published_run(dataset)
    except Exception as exc:
        log.warning("Dashboard warm-up skipped: publication check failed (%s)", exc)
        return
    if not published:
        log.info("Dashboard warm-up skipped: %s has no published run.", dataset)
        return
    try:
        refresh_dashboard_cache(dataset)
    except Exception as exc:
        log.warning("Dashboard warm-up failed for %s: %s", dataset, exc)


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
        # First cycle shortly after boot so end users see the Scheduler service
        # in Observability without waiting a full interval. Delayed 90 s on
        # purpose: the boot dashboard warm-up scans Parquet, and overlapping
        # two scans on a 512 MB instance is what causes 502 restarts.
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=90),
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

    # Dashboard cache (§19): freshness is event-driven, not timer-driven.
    # Publish invalidates and rebuilds its own dataset, reset clears everything,
    # and dataset delete drops that dataset's row. The old 15-minute blanket
    # wipe just forced a full Parquet rebuild on the next page view, so it is
    # deliberately not scheduled.
    _scheduler.start()
    # Warm the cache once at boot, but only when a published dataset exists.
    from threading import Thread

    Thread(
        target=_warm_published_dashboard,
        name="dashboard_cache_first",
        daemon=True,
    ).start()
    log.info(
        "Scheduler started: controller every %s min, retention every 24h; "
        "dashboard cache refresh is event-driven",
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
