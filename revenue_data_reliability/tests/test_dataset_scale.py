"""Unit tests for lazy dataset scale info (no S3 / Postgres round trips)."""

from backend.services import dataset_scale as scale


def test_months_between_is_inclusive():
    assert scale._months_between("2024-01", "2028-12") == 60
    assert scale._months_between("2024-01-01", "2024-03-01") == 3
    assert scale._months_between("2026-10", "2026-10") == 1


def test_months_between_rejects_bad_values():
    assert scale._months_between(None, "2024-01") is None
    assert scale._months_between("not-a-month", "2024-01") is None
    assert scale._months_between("2024-03", "2024-01") is None


def test_formatters_match_ui_contract():
    assert scale.format_rows(1234) == "1,234"
    assert scale.format_rows(31_516_292) == "31,516,292"
    assert scale.format_months(60) == "60"
    assert scale.format_size(12_400_000) == "12.4 MB"
    assert scale.format_rows(None) is None
    assert scale.format_months(None) is None
    assert scale.format_size(None) is None


def test_cached_scale_reads_dict_and_json_manifest():
    payload = {"version": 1, "scenario": "baseline_run", "rows": 10, "months": 2, "size_bytes": 3}
    assert scale.cached_scale({"scale": payload}) == payload
    assert scale.cached_scale('{"scale": {"version": 1, "rows": 10}}') is not None
    assert scale.cached_scale({"scale": {"version": 0, "rows": 10}}) is None
    assert scale.cached_scale({"scale": {"version": 1}}) is None
    assert scale.cached_scale(None) is None


def test_scale_sql_reads_footers_only():
    sql = scale.scale_sql("baseline_run")
    assert "parquet_file_metadata(" in sql
    assert "parquet_metadata(" in sql
    assert "read_parquet" not in sql
    assert "scenarios/baseline_run/*.parquet" in sql


def test_attach_uses_cached_manifest_without_computing(monkeypatch):
    def _fail(*_args, **_kwargs):
        raise AssertionError("cached scenarios must not be recomputed")

    monkeypatch.setattr(scale, "_compute_and_cache", _fail)
    scenarios = [
        {
            "name": "baseline_run",
            "source_scenario": "baseline_run",
            "manifest": {
                "scale": {
                    "version": 1,
                    "scenario": "baseline_run",
                    "rows": 1234,
                    "months": 60,
                    "size_bytes": 12_400_000,
                }
            },
        }
    ]

    scale.attach_scale_info(scenarios)

    assert scenarios[0]["rows"] == "1,234"
    assert scenarios[0]["months"] == "60"
    assert scenarios[0]["size"] == "12.4 MB"


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
            "manifest": {
                "scale": {
                    "version": 1,
                    "scenario": "baseline_run",
                    "rows": 1234,
                    "months": 60,
                    "size_bytes": 12_400_000,
                }
            },
        }
    ]

    scale.attach_scale_info(scenarios, timeout=0.01)

    assert scenarios[0]["rows"] is None
