"""Exception service (raw SQL over Postgres)."""

import json
from datetime import datetime

from backend.db.connection import fetch_all, fetch_one


def _fmt_dt(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def _as_json(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return value
    return value


def create_exception(
    run_id,
    exc_type,
    severity,
    title,
    period=None,
    trace_id=None,
    status="open",
    rule_id=None,
    details=None,
):
    row = fetch_one(
        """
        INSERT INTO exceptions (run_id, type, severity, period, title, status, trace_id, rule_id, details)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING exception_id
        """,
        (
            run_id,
            exc_type,
            severity,
            period,
            title,
            status,
            trace_id,
            rule_id,
            json.dumps(details, default=str) if details is not None else None,
        ),
    )
    return row["exception_id"]


def _to_dict(r):
    return {
        "id": r["exception_id"],
        "run_id": r["run_id"],
        "type": r["type"],
        "severity": r["severity"],
        "period": r["period"],
        "title": r["title"],
        "status": r["status"],
        "trace_id": r["trace_id"],
        "rule_id": r.get("rule_id"),
        "details": _as_json(r.get("details")),
        "created_at": _fmt_dt(r["created_at"]),
    }


def get_exception(exc_id):
    r = fetch_one("SELECT * FROM exceptions WHERE exception_id = %s", (exc_id,))
    if not r:
        return None
    return _to_dict(r)


def list_exceptions():
    rows = fetch_all(
        "SELECT * FROM exceptions ORDER BY created_at DESC, exception_id DESC"
    )
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
    """Return sampled failures for the rule that raised a validation exception."""
    if not exc or not exc.get("run_id"):
        return []
    rule_id = exc.get("rule_id") or "VAL_FK_ITEM_EXISTS"
    row = fetch_one(
        "SELECT sampled_failures FROM validations WHERE run_id = %s AND rule_id = %s",
        (exc["run_id"], rule_id),
    )
    if not row or not row.get("sampled_failures"):
        return []
    sf = _as_json(row["sampled_failures"])
    return sf if isinstance(sf, list) else []


def get_quarantine_records_for_exception(exc):
    """Return the affected records (dicts) to quarantine for an exception.

    Prefers the structured sample persisted in ``exceptions.details``,
    falling back to the validation rule's sampled failures.
    """
    if not exc:
        return []
    details = _as_json(exc.get("details")) if isinstance(exc.get("details"), (str, dict)) else None
    sample = []
    if isinstance(details, dict):
        raw = details.get("sample") or details.get("records")
        if isinstance(raw, list):
            sample = [r for r in raw if isinstance(r, dict) or _is_scalar_key(r)]
    if sample:
        return sample
    return get_sampled_failures_for_exception(exc)


def _is_scalar_key(value):
    try:
        int(value)
        return True
    except (TypeError, ValueError):
        return False


def get_reconciliation_rows_for_exception(exc):
    """Return the monthly reconciliation rows behind a reconciliation exception."""
    if not exc or not exc.get("run_id"):
        return []
    params = [exc["run_id"]]
    sql = (
        "SELECT period, account_id, item_category, billings, gl, variance_pct, status "
        "FROM reconciliations WHERE run_id = %s"
    )
    if exc.get("period"):
        sql += " AND period = %s"
        params.append(exc["period"])
    sql += " ORDER BY period, account_id, item_category"
    rows = fetch_all(sql, tuple(params))
    out = []
    for r in rows:
        out.append(
            {
                "period": r["period"],
                "account_id": r["account_id"],
                "item_category": r["item_category"],
                "billings": float(r["billings"]) if r["billings"] is not None else None,
                "gl": float(r["gl"]) if r["gl"] is not None else None,
                "variance_pct": (
                    float(r["variance_pct"]) if r["variance_pct"] is not None else None
                ),
                "status": r["status"],
            }
        )
    return out
