"""Exception service (raw SQL over Postgres)."""

from datetime import datetime

from backend.db.connection import execute, fetch_all, fetch_one


def _fmt_dt(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def create_exception(run_id, exc_type, severity, title, period=None, trace_id=None, status="open"):
    row = fetch_one(
        """
        INSERT INTO exceptions (run_id, type, severity, period, title, status, trace_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING exception_id
        """,
        (run_id, exc_type, severity, period, title, status, trace_id),
    )
    return row["exception_id"]


def get_exception(exc_id):
    r = fetch_one("SELECT * FROM exceptions WHERE exception_id = %s", (exc_id,))
    if not r:
        return None
    return {
        "id": r["exception_id"],
        "run_id": r["run_id"],
        "type": r["type"],
        "severity": r["severity"],
        "period": r["period"],
        "title": r["title"],
        "status": r["status"],
        "trace_id": r["trace_id"],
        "created_at": _fmt_dt(r["created_at"]),
    }


def list_exceptions():
    rows = fetch_all("SELECT * FROM exceptions ORDER BY created_at DESC, exception_id DESC")
    out = []
    for r in rows:
        out.append(
            {
                "id": r["exception_id"],
                "run_id": r["run_id"],
                "type": r["type"],
                "severity": r["severity"],
                "period": r["period"],
                "title": r["title"],
                "status": r["status"],
                "trace_id": r["trace_id"],
            }
        )
    return out


def get_sampled_failures_for_exception(exc):
    # Find validation linked to the run for VAL_FK_ITEM_EXISTS
    if not exc or not exc.get("run_id"):
        return []
    row = fetch_one(
        """
        SELECT sampled_failures FROM validations
        WHERE run_id = %s AND rule_id = 'VAL_FK_ITEM_EXISTS'
        """,
        (exc["run_id"],),
    )
    if not row or not row.get("sampled_failures"):
        return []
    sf = row["sampled_failures"]
    if isinstance(sf, str):
        import json
        try:
            sf = json.loads(sf)
        except Exception:
            return []
    return sf if isinstance(sf, list) else []
