"""In-app data reset utilities (preserve baseline fixture)."""
from __future__ import annotations

from dataclasses import dataclass

from backend.db import execute, fetch_all, fetch_one
from backend.db.fixture import ensure_baseline_fixture


@dataclass
class ResetSummary:
    baseline_run_id: int | None
    runs_deleted: int
    publications_deleted: int
    messages_deleted: int
    discussions_deleted: int
    scenarios_deleted: int


def reset_preserve_baseline() -> ResetSummary:
    """Reset non-baseline data while preserving personas, rules, and baseline fixture."""
    row = fetch_one("SELECT run_id FROM runs WHERE scenario_name='baseline_run' ORDER BY run_id LIMIT 1")
    baseline_run_id = row["run_id"] if row else None

    execute(
        "TRUNCATE TABLE validations, reconciliations, exceptions, quarantines, approvals, "
        "alerts, agent_actions, otel_spans, otel_logs, otel_metrics, dashboard_cache CASCADE"
    )

    messages_deleted = _delete_messages_non_baseline()
    discussions_deleted = _delete_discussions_non_baseline()
    publications_deleted = _delete_publications_non_baseline()
    runs_deleted = _delete_runs_non_baseline()
    scenarios_deleted = _delete_scenarios_non_baseline()

    ensure_baseline_fixture()

    return ResetSummary(
        baseline_run_id=baseline_run_id,
        runs_deleted=runs_deleted,
        publications_deleted=publications_deleted,
        messages_deleted=messages_deleted,
        discussions_deleted=discussions_deleted,
        scenarios_deleted=scenarios_deleted,
    )


def _delete_messages_non_baseline() -> int:
    res = execute(
        "DELETE FROM messages WHERE discussion_id NOT IN ("
        "  SELECT discussion_id FROM discussions d "
        "  JOIN runs r ON r.run_id::text = d.anchor_id "
        "  WHERE d.anchor_type='run' AND r.scenario_name='baseline_run' AND r.published=TRUE"
        ") RETURNING discussion_id",
        fetch=True,
    )
    if res:
        cols, rows = res
        return len(rows) if rows else 0
    return 0


def _delete_discussions_non_baseline() -> int:
    res = execute(
        "DELETE FROM discussions WHERE anchor_type='run' AND anchor_id NOT IN ("
        "  SELECT run_id::text FROM runs WHERE scenario_name='baseline_run' AND published=TRUE"
        ") RETURNING discussion_id",
        fetch=True,
    )
    if res:
        cols, rows = res
        return len(rows) if rows else 0
    return 0


def _delete_publications_non_baseline() -> int:
    res = execute(
        "DELETE FROM publications WHERE run_id NOT IN ("
        "  SELECT run_id FROM runs WHERE scenario_name='baseline_run' AND published=TRUE"
        ") RETURNING publication_id",
        fetch=True,
    )
    if res:
        cols, rows = res
        return len(rows) if rows else 0
    return 0


def _delete_runs_non_baseline() -> int:
    res = execute(
        "DELETE FROM runs WHERE scenario_name IS DISTINCT FROM 'baseline_run' "
        "OR published = FALSE RETURNING run_id",
        fetch=True,
    )
    if res:
        cols, rows = res
        return len(rows) if rows else 0
    return 0


def _delete_scenarios_non_baseline() -> int:
    res = execute(
        "DELETE FROM scenarios WHERE name <> 'baseline_run' RETURNING name",
        fetch=True,
    )
    if res:
        cols, rows = res
        return len(rows) if rows else 0
    return 0
