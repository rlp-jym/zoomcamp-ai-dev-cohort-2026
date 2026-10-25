"""Scheduler cadence and dashboard cache freshness (no S3, no destructive jobs)."""


def test_scheduler_no_longer_wipes_dashboard_cache(monkeypatch):
    from backend.services import scheduler as sched

    monkeypatch.setattr(sched, "_scheduler", None)
    monkeypatch.setattr(sched, "_warm_published_dashboard", lambda: None)

    scheduler = sched.start_scheduler()
    try:
        job_ids = {job.id for job in scheduler.get_jobs()}
        assert "dashboard_refresh" not in job_ids
        assert job_ids == {"controller_verification", "otel_retention"}
    finally:
        scheduler.shutdown(wait=False)
        sched._scheduler = None


def test_boot_warm_up_skips_without_published_run(monkeypatch):
    from backend.services import dashboard, publications, runs
    from backend.services import scheduler as sched

    refreshes = []
    monkeypatch.setattr(runs, "default_dataset", lambda: "baseline_run")
    monkeypatch.setattr(publications, "get_published_run", lambda name: None)
    monkeypatch.setattr(
        dashboard,
        "refresh_dashboard_cache",
        lambda *args, **kwargs: refreshes.append(args),
    )

    sched._warm_published_dashboard()

    assert refreshes == []


def test_boot_warm_up_refreshes_published_dataset(monkeypatch):
    from backend.services import dashboard, publications, runs
    from backend.services import scheduler as sched

    refreshes = []
    monkeypatch.setattr(runs, "default_dataset", lambda: "generated_seed101_y1")
    monkeypatch.setattr(
        publications, "get_published_run", lambda name: {"id": 1, "dataset": name}
    )
    monkeypatch.setattr(
        dashboard,
        "refresh_dashboard_cache",
        lambda *args, **kwargs: refreshes.append(args),
    )

    sched._warm_published_dashboard()

    assert refreshes == [("generated_seed101_y1",)]


def test_dashboard_memory_ttl_is_at_least_a_minute():
    from backend.services import dashboard

    assert dashboard._DASHBOARD_CACHE_TTL >= 60


def test_scenarios_tab_is_hidden_from_navigation():
    from backend.config import TEMPLATES_DIR

    base = (TEMPLATES_DIR / "base.html").read_text(encoding="utf-8")
    assert 'href="/scenarios"' not in base

    dashboard = (TEMPLATES_DIR / "dashboard.html").read_text(encoding="utf-8")
    assert "Start a scenario analysis" not in dashboard
