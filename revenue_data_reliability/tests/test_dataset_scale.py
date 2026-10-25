"""Unit tests for lazy dataset scale info (no S3 / Postgres round trips)."""

import pytest

from backend.services import dataset_scale as scale

BASE_ROWS = 31_497_522
BASE_BYTES = 430_691_108


@pytest.fixture(autouse=True)
def _pin_previous_month(monkeypatch):
    """Freeze the scale window so expectations do not drift with today's date."""
    monkeypatch.setattr(scale, "_previous_month_end", lambda: (2026, 9))


def test_parse_years_from_generated_names():
    assert scale.parse_years_to_backtrack("generated_seed101_y1") == 1
    assert scale.parse_years_to_backtrack("generated_seed102_y3") == 3
    assert scale.parse_years_to_backtrack("baseline_seed9_y5") == 5
    assert scale.parse_years_to_backtrack("baseline_run") is None
    assert scale.parse_years_to_backtrack(None) is None


def test_scale_window_is_trailing_years():
    assert scale.scale_window(1) == ("2025-10", "2026-09")
    assert scale.scale_window(3) == ("2023-10", "2026-09")
    assert scale.scale_window(5) == ("2021-10", "2026-09")


def test_months_between_is_inclusive():
    assert scale._months_between("2024-01", "2028-12") == 60
    assert scale._months_between("2024-01-01", "2024-03-01") == 3
    assert scale._months_between("2026-10", "2026-10") == 1


def test_months_between_rejects_bad_values():
    assert scale._months_between(None, "2024-01") is None
    assert scale._months_between("not-a-month", "2024-01") is None
    assert scale._months_between("2024-03", "2024-01") is None


def test_windowed_scale_keeps_full_baseline():
    result = scale.windowed_scale(BASE_ROWS, BASE_BYTES, "2021-10", "2026-09", 5)
    assert result == {"rows": BASE_ROWS, "months": 60, "size_bytes": BASE_BYTES}


def test_windowed_scale_shortens_one_year_clone():
    result = scale.windowed_scale(BASE_ROWS, BASE_BYTES, "2021-10", "2026-09", 1)
    assert result["months"] == 12
    assert result["rows"] == round(BASE_ROWS * 12 / 60)
    assert result["size_bytes"] == round(BASE_BYTES * 12 / 60)


def test_windowed_scale_shortens_three_year_clone():
    result = scale.windowed_scale(BASE_ROWS, BASE_BYTES, "2021-10", "2026-09", 3)
    assert result["months"] == 36
    assert result["rows"] == round(BASE_ROWS * 36 / 60)
    assert result["size_bytes"] == round(BASE_BYTES * 36 / 60)


def test_windowed_scale_handles_already_windowed_source():
    # A y1 source physically holding only 12 months reports all of them.
    result = scale.windowed_scale(12_813_555, 176_944_070, "2025-10", "2026-09", 1)
    assert result["months"] == 12
    assert result["rows"] == 12_813_555


def test_windowed_scale_without_years_or_stats():
    full = scale.windowed_scale(BASE_ROWS, BASE_BYTES, "2021-10", "2026-09", None)
    assert full["months"] == 60
    assert full["rows"] == BASE_ROWS
    no_stats = scale.windowed_scale(BASE_ROWS, BASE_BYTES, None, None, 3)
    assert no_stats["months"] == 36
    assert no_stats["rows"] == BASE_ROWS


def test_formatters_match_ui_contract():
    assert scale.format_rows(1234) == "1,234"
    assert scale.format_rows(31_497_522) == "31,497,522"
    assert scale.format_months(60) == "60"
    assert scale.format_size(12_400_000) == "12.4 MB"
    assert scale.format_rows(None) is None
    assert scale.format_months(None) is None
    assert scale.format_size(None) is None


def test_cached_scale_reads_dict_and_json_manifest():
    payload = {
        "version": scale.SCALE_VERSION,
        "scenario": "baseline_run",
        "years_to_backtrack": 5,
        "rows": 10,
        "months": 2,
        "size_bytes": 3,
    }
    assert scale.cached_scale({"scale": payload}) == payload
    assert (
        scale.cached_scale(
            f'{{"scale": {{"version": {scale.SCALE_VERSION}, "rows": 10}}}}'
        )
        is not None
    )
    assert scale.cached_scale({"scale": {"version": 1, "rows": 10}}) is None
    assert scale.cached_scale({"scale": {"version": scale.SCALE_VERSION}}) is None
    assert scale.cached_scale(None) is None


def test_scale_sql_reads_footers_only_and_windows_period():
    sql = scale.scale_sql("baseline_run", 1)
    assert "parquet_file_metadata(" in sql
    assert "parquet_metadata(" in sql
    assert "read_parquet" not in sql
    assert "scenarios/baseline_run/*.parquet" in sql
    window_start, window_end = scale.scale_window(1)
    assert f"p.max_period >= '{window_start}'" in sql
    assert f"p.min_period <= '{window_end}'" in sql


def test_attach_uses_cached_manifest_without_computing(monkeypatch):
    def _fail(*_args, **_kwargs):
        raise AssertionError("cached scenarios must not be recomputed")

    monkeypatch.setattr(scale, "_compute_and_cache", _fail)
    scenarios = [
        {
            "name": "generated_seed101_y1",
            "source_scenario": "baseline_run",
            "years_to_backtrack": 1,
            "manifest": {
                "scale": {
                    "version": scale.SCALE_VERSION,
                    "scenario": "baseline_run",
                    "years_to_backtrack": 1,
                    "rows": 1234,
                    "months": 12,
                    "size_bytes": 12_400_000,
                }
            },
        }
    ]

    scale.attach_scale_info(scenarios)

    assert scenarios[0]["rows"] == "1,234"
    assert scenarios[0]["months"] == "12"
    assert scenarios[0]["size"] == "12.4 MB"


def test_attach_ignores_cache_with_a_different_year_window(monkeypatch):
    def _noop(pending, results):
        with scale._inflight_lock:
            scale._inflight.difference_update(p["name"] for p in pending)

    monkeypatch.setattr(scale, "_compute_and_cache", _noop)
    scenarios = [
        {
            "name": "generated_seed101_y1",
            "source_scenario": "baseline_run",
            "years_to_backtrack": 1,
            "manifest": {
                "scale": {
                    "version": scale.SCALE_VERSION,
                    "scenario": "baseline_run",
                    "years_to_backtrack": 5,
                    "rows": BASE_ROWS,
                    "months": 60,
                    "size_bytes": BASE_BYTES,
                }
            },
        }
    ]

    scale.attach_scale_info(scenarios, timeout=0.01)

    assert scenarios[0]["rows"] is None


def test_attach_renders_dash_when_read_does_not_finish(monkeypatch):
    def _slow_noop(pending, results):
        with scale._inflight_lock:
            scale._inflight.difference_update(p["name"] for p in pending)

    monkeypatch.setattr(scale, "_compute_and_cache", _slow_noop)
    scenarios = [{"name": "slow_run", "source_scenario": "slow_run", "manifest": None}]

    scale.attach_scale_info(scenarios, timeout=0.01)

    assert scenarios[0]["rows"] is None
    assert scenarios[0]["months"] is None
    assert scenarios[0]["size"] is None


def test_attach_ignores_cache_from_a_different_source(monkeypatch):
    def _noop(pending, results):
        with scale._inflight_lock:
            scale._inflight.difference_update(p["name"] for p in pending)

    monkeypatch.setattr(scale, "_compute_and_cache", _noop)
    scenarios = [
        {
            "name": "generated_seed1_y2",
            "source_scenario": "generated_seed1_y2",
            "years_to_backtrack": 2,
            "manifest": {
                "scale": {
                    "version": scale.SCALE_VERSION,
                    "scenario": "baseline_run",
                    "years_to_backtrack": 2,
                    "rows": 1234,
                    "months": 24,
                    "size_bytes": 12_400_000,
                }
            },
        }
    ]

    scale.attach_scale_info(scenarios, timeout=0.01)

    assert scenarios[0]["rows"] is None

