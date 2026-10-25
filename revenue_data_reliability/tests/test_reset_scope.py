"""Reset scope: dataset state is cleared, audit and telemetry survive."""

from backend.db.reset import RESET_PRESERVED_TABLES, RESET_TRUNCATE_TABLES


def test_reset_truncates_dataset_scoped_tables_only():
    assert set(RESET_TRUNCATE_TABLES) == {
        "validations",
        "reconciliations",
        "exceptions",
        "quarantines",
        "dashboard_cache",
    }


def test_reset_preserves_audit_and_telemetry():
    assert set(RESET_PRESERVED_TABLES) == {
        "agent_actions",
        "approvals",
        "alerts",
        "otel_spans",
        "otel_logs",
        "otel_metrics",
    }


def test_reset_scopes_do_not_overlap():
    assert not set(RESET_TRUNCATE_TABLES) & set(RESET_PRESERVED_TABLES)
