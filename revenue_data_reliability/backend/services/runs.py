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
        INSERT INTO runs (scenario_name, status, started_at, triggered_by, trace_id)
        VALUES (%s, 'running', now(), %s, %s)
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


def list_runs():
    rows = fetch_all("SELECT * FROM runs ORDER BY created_at DESC, run_id DESC")
    out = []
    for r in rows:
        out.append(
            {
                "id": r["run_id"],
                "scenario": r["scenario_name"],
                "status": r["status"],
                "started_at": _fmt_dt(r["started_at"]),
                "duration": r["duration"] if r["duration"] else "-",
                "published": r["published"],
            }
        )
    return out


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
        "status", "finished_at", "duration", "validations_total",
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


def reject_run(run_id, persona_id, trace_id=None, comment=None):
    execute("UPDATE runs SET status = 'rejected' WHERE run_id = %s", (run_id,))
    execute(
        """
        INSERT INTO approvals (target_type, target_id, persona_id, decision, comment, trace_id)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        ("run", str(run_id), persona_id, "rejected", comment, trace_id),
    )
