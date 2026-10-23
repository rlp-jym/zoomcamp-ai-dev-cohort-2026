"""Run service (raw SQL over Postgres)."""

from datetime import datetime

from backend.db.connection import execute, fetch_all, fetch_one


def _fmt_dt(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def create_run(scenario_name, triggered_by, trace_id):
    row = fetch_one(
        """
        INSERT INTO runs (scenario_name, status, current_stage, progress_percent,
                          started_at, triggered_by, trace_id)
        VALUES (%s, 'running', 'Queued', 0, now(), %s, %s)
        RETURNING run_id
        """,
        (scenario_name, triggered_by, trace_id),
    )
    return row["run_id"]


def get_run(run_id):
    r = fetch_one("SELECT * FROM runs WHERE run_id = %s", (run_id,))
    if not r:
        return None
    return {
        "id": r["run_id"],
        "scenario": r["scenario_name"],
        "status": r["status"],
        "current_stage": r.get("current_stage"),
        "progress_percent": r.get("progress_percent"),
        "error_message": r.get("error_message"),
        "duration_seconds": r.get("duration_seconds"),
        "started_at": _fmt_dt(r["started_at"]),
        "finished_at": _fmt_dt(r["finished_at"]),
        "duration": r["duration"],
        "triggered_by": r["triggered_by"],
        "trace_id": r["trace_id"],
        "validations_total": r["validations_total"],
        "validations_failed": r["validations_failed"],
        "exceptions_created": r["exceptions_created"],
        "published": r["published"],
        "published_at": _fmt_dt(r["published_at"]),
        "approved_at": _fmt_dt(r["approved_at"]),
    }


def list_runs(scenario_name=None):
    if scenario_name:
        rows = fetch_all(
            "SELECT * FROM runs WHERE scenario_name = %s ORDER BY created_at DESC, run_id DESC",
            (scenario_name,),
        )
    else:
        rows = fetch_all("SELECT * FROM runs ORDER BY created_at DESC, run_id DESC")
    out = []
    for r in rows:
        out.append(
            {
                "id": r["run_id"],
                "scenario": r["scenario_name"],
                "status": r["status"],
                "current_stage": r.get("current_stage"),
                "progress_percent": r.get("progress_percent"),
                "duration_seconds": r.get("duration_seconds"),
                "started_at": _fmt_dt(r["started_at"]),
                "duration": r["duration"] if r["duration"] else "-",
                "published": r["published"],
            }
        )
    return out


def resolve_active_run(scenario_name):
    """Latest completed run for a dataset (scenario). Returns run_id or None."""
    if not scenario_name:
        return None
    r = fetch_one(
        "SELECT run_id FROM runs "
        "WHERE scenario_name = %s AND status = 'completed' "
        "ORDER BY finished_at DESC NULLS LAST, run_id DESC LIMIT 1",
        (scenario_name,),
    )
    return r["run_id"] if r else None


def default_scenario():
    """Scenario of the most recently completed run, else first scenario."""
    r = fetch_one(
        "SELECT scenario_name FROM runs WHERE status = 'completed' "
        "ORDER BY finished_at DESC NULLS LAST, run_id DESC LIMIT 1"
    )
    if r and r.get("scenario_name"):
        return r["scenario_name"]
    r = fetch_one("SELECT name FROM scenarios ORDER BY created_at DESC, name LIMIT 1")
    return r["name"] if r else "baseline_run"


def sweep_stale_runs(max_age_minutes: int = 30) -> int:
    """Mark orphaned 'running' runs as failed (e.g. after a crash/restart)."""
    res = execute(
        "UPDATE runs SET status='failed', finished_at=now() "
        "WHERE status='running' AND started_at < now() - make_interval(mins => %s) "
        "RETURNING run_id",
        (max_age_minutes,),
        fetch=True,
    )
    if res:
        _cols, rows = res
        return len(rows) if rows else 0
    return 0


def update_run(run_id, **fields):
    if not fields:
        return
    allowed = {
        "status", "current_stage", "progress_percent", "error_message",
        "duration_seconds", "finished_at", "duration", "validations_total",
        "validations_failed", "exceptions_created", "published", "published_at",
        "approved_at", "trace_id",
    }
    sets = []
    params = []
    for k, v in fields.items():
        if k not in allowed:
            continue
        sets.append(f"{k} = %s")
        params.append(v)
    if not sets:
        return
    params.append(run_id)
    execute(f"UPDATE runs SET {', '.join(sets)} WHERE run_id = %s", tuple(params))


def approve_run(run_id, persona_id, trace_id=None, comment=None):
    execute(
        "UPDATE runs SET approved_at = now() WHERE run_id = %s",
        (run_id,),
    )
    execute(
        """
        INSERT INTO approvals (target_type, target_id, persona_id, decision, comment, trace_id)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        ("run", str(run_id), persona_id, "approved", comment, trace_id),
    )


def reconcile_failed_run(run_id):
    rid = int(run_id)
    row = fetch_one("SELECT status FROM runs WHERE run_id = %s", (rid,))
    if not row or row.get("status") != "failed":
        return False
    v = fetch_one("SELECT COUNT(*) AS c FROM validations WHERE run_id = %s", (rid,))
    if v and (v.get("c") or 0) > 0:
        update_run(rid, status="completed", current_stage="Complete", progress_percent=100)
        return True
    return False


def _run_anchor_filter():
    """SQL predicate matching discussions/actions owned by a run.

    Reads the run id from two parameters: the run's own anchor id and the
    exception ids that belong to the run.
    """
    return """
        (anchor_type = 'run' AND anchor_id = %s)
        OR (
            anchor_type = 'exception'
            AND anchor_id IN (
                SELECT CAST(exception_id AS TEXT) FROM exceptions WHERE run_id = %s
            )
        )
    """


def delete_run(run_id):
    rid = int(run_id)
    srid = str(run_id)
    anchor_filter = _run_anchor_filter()
    # Remove messages and discussions for the run thread and every exception
    # thread raised by this run before deleting the exceptions themselves.
    execute(
        f"""
        DELETE FROM messages
        WHERE discussion_id IN (
            SELECT discussion_id FROM discussions WHERE {anchor_filter}
        )
        """,
        (srid, rid),
    )
    execute(
        f"DELETE FROM discussions WHERE {anchor_filter}",
        (srid, rid),
    )
    execute(
        f"DELETE FROM agent_actions WHERE {anchor_filter}",
        (srid, rid),
    )
    execute("DELETE FROM validations WHERE run_id = %s", (rid,))
    execute("DELETE FROM exceptions WHERE run_id = %s", (rid,))
    execute("DELETE FROM reconciliations WHERE run_id = %s", (rid,))
    execute("DELETE FROM quarantines WHERE run_id = %s", (rid,))
    execute("DELETE FROM approvals WHERE target_type = 'run' AND target_id = %s", (srid,))
    execute("DELETE FROM publications WHERE run_id = %s", (rid,))
    execute("DELETE FROM runs WHERE run_id = %s", (rid,))


def reject_run(run_id, persona_id, trace_id=None, comment=None):
    execute("UPDATE runs SET status = 'rejected' WHERE run_id = %s", (run_id,))
    execute(
        """
        INSERT INTO approvals (target_type, target_id, persona_id, decision, comment, trace_id)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        ("run", str(run_id), persona_id, "rejected", comment, trace_id),
    )
