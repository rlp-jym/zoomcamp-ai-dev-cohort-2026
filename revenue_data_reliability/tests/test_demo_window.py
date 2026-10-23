"""Tests for the deterministic latest-12-months scan window."""

from backend.services.demo_window import demo_window


def test_demo_window_is_latest_twelve_months():
    window = demo_window()
    assert window.start_period == "2026-01"
    assert window.end_period == "2026-12"
    assert window.start_date == "2026-01-01"
    assert window.end_date == "2027-01-01"


def test_years_to_backtrack_cannot_widen_demo_window():
    assert demo_window(1) == demo_window(5)
    assert demo_window(9) == demo_window()


def test_validation_render_applies_period_and_date_filters():
    from backend.services.validations import _render_sql

    rendered = _render_sql(
        "SELECT * FROM read_parquet("
        "'s3://{bucket}/scenarios/{scenario}/invoices.parquet') inv "
        "WHERE inv.invoice_date >= DATE '{window_start_date}' "
        "AND inv.invoice_date < DATE '{window_end_date}' "
        "AND period >= '{window_start_period}'",
        "baseline_run",
        years_to_backtrack=5,
    )

    assert "inv.invoice_date >= DATE '2026-01-01'" in rendered
    assert "inv.invoice_date < DATE '2027-01-01'" in rendered
    assert "period >= '2026-01'" in rendered
    assert "s3://" not in rendered


def test_reconciliation_sql_has_window_placeholders():
    from backend.services.reconciliations import RECON_SQL

    rendered = RECON_SQL.format(
        bucket="bucket",
        scenario="baseline_run",
        window_start_period="2026-01",
        window_end_period="2026-12",
        window_start_date="2026-01-01",
        window_end_date="2027-01-01",
    )

    assert "inv.invoice_date >= DATE '2026-01-01'" in rendered
    assert "period >= '2026-01'" in rendered

