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


def test_topbar_is_sticky():
    from backend.config import STATIC_DIR

    css = (STATIC_DIR / "css" / "app.css").read_text(encoding="utf-8")
    topbar = css.split(".topbar {", 1)[1].split("}", 1)[0]
    assert "position: sticky" in topbar
    assert "top: 0" in topbar
    assert "flex-wrap: wrap" in topbar


def test_span_exporter_drops_body_send_spans(monkeypatch):
    from types import SimpleNamespace

    from backend.db import connection
    from observability.exporter import PostgresSpanExporter

    def _span(name, attributes):
        return SimpleNamespace(
            name=name,
            attributes=attributes,
            instrumentation_scope=None,
            resource=None,
            status=None,
            parent=None,
            context=SimpleNamespace(span_id=1, trace_id=2),
            start_time=1,
            end_time=2_000_000,
        )

    spans = [
        _span("GET /x", {}),
        _span("GET /x http send", {"asgi.event.type": "http.response.start"}),
        _span("GET /x http send", {"asgi.event.type": "http.response.body"}),
    ]

    captured = []

    def _execute_many(_sql, rows):
        captured.append(rows)

    monkeypatch.setattr(connection, "execute_many", _execute_many)

    result = PostgresSpanExporter().export(spans)

    assert result.name == "SUCCESS"
    assert len(captured) == 1
    rows = captured[0]
    assert len(rows) == 2
    assert all("http.response.body" not in row[8] for row in rows)
    names = [row[3] for row in rows]
    assert names.count("GET /x http send") == 1
    assert "GET /x" in names


def test_metrics_series_returns_hourly_labels(monkeypatch):
    from datetime import datetime

    from backend.services import observability

    rows = [
        {"bucket": datetime(2026, 10, 24, 9, 0), "avg_active": 1.234, "max_active": 3},
        {"bucket": datetime(2026, 10, 24, 10, 0), "avg_active": 2, "max_active": 5.678},
    ]
    monkeypatch.setattr(observability, "fetch_all", lambda *args, **kwargs: rows)

    series = observability.metrics_series()

    assert series["labels"] == ["09:00", "10:00"]
    assert all(isinstance(value, float) for value in series["avg"])
    assert all(isinstance(value, float) for value in series["max"])
    assert series["avg"] == [1.23, 2.0]
    assert series["max"] == [3.0, 5.68]

