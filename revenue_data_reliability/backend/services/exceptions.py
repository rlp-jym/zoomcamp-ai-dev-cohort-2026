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
        "scenario_name": r.get("scenario_name"),
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
    r = fetch_one(
        """
        SELECT e.*, r.scenario_name AS scenario_name
        FROM exceptions e
        LEFT JOIN runs r ON r.run_id = e.run_id
        WHERE e.exception_id = %s
        """,
        (exc_id,),
    )
    if not r:
        return None
    return _to_dict(r)


def list_exceptions(status=None, limit=50, offset=0, run_id=None):
    """List exceptions, optionally filtered by status bucket and/or run.

    Default (None/'open') returns only non-resolved rows so the page stays
    a pending work queue; 'resolved' returns closed rows and 'all' returns
    everything. Pass ``run_id`` to restrict results to a single validation
    run. Results are bounded by ``limit`` (default 50) with ``offset``
    for pagination to avoid rendering unbounded result sets.
    """
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 50
    try:
        offset = int(offset)
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 50
    if offset < 0:
        offset = 0
    try:
        run_id = int(run_id) if run_id not in (None, "") else None
    except (TypeError, ValueError):
        run_id = None
    conditions = []
    params = []
    if status in (None, "", "open"):
        conditions.append("e.status <> 'resolved'")
    elif status == "resolved":
        conditions.append("e.status = 'resolved'")
    if run_id is not None:
        conditions.append("e.run_id = %s")
        params.append(run_id)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    rows = fetch_all(
        f"SELECT e.*, r.scenario_name AS scenario_name "
        f"FROM exceptions e LEFT JOIN runs r ON r.run_id = e.run_id "
        f"{where} ORDER BY e.created_at DESC, e.exception_id DESC "
        f"LIMIT %s OFFSET %s",
        tuple(params + [limit, offset]),
    )
    out = []
    for r in rows:
        out.append(
            {
                "id": r["exception_id"],
                "run_id": r["run_id"],
                "scenario_name": r.get("scenario_name"),
                "type": r["type"],
                "severity": r["severity"],
                "period": r["period"],
                "title": r["title"],
                "status": r["status"],
                "trace_id": r["trace_id"],
            }
        )
    return out


def exception_counts():
    r = fetch_one(
        """
        SELECT COUNT(*) FILTER (WHERE status <> 'resolved') AS open_n,
               COUNT(*) FILTER (WHERE status = 'resolved') AS resolved_n,
               COUNT(*) AS total
        FROM exceptions
        """
    )
    if not r:
        return {"open": 0, "resolved": 0, "total": 0}
    return {"open": r["open_n"], "resolved": r["resolved_n"], "total": r["total"]}


def exception_trend(run_id=None):
    """Per-period detected/resolved/open counts for a run (latest if None)."""
    if run_id is None:
        r = fetch_one("SELECT run_id FROM runs WHERE status = 'completed' ORDER BY run_id DESC LIMIT 1")
        if not r:
            return {"labels": [], "detected": [], "resolved": [], "open": [], "cumulative": []}
        run_id = r["run_id"]
    rows = fetch_all(
        """
        SELECT COALESCE(period, 'undated') AS period,
               COUNT(*) AS detected,
               COUNT(*) FILTER (WHERE status = 'resolved') AS resolved,
               COUNT(*) FILTER (WHERE status <> 'resolved') AS open
        FROM exceptions
        WHERE run_id = %s
        GROUP BY 1
        """,
        (run_id,),
    )
    rows.sort(key=lambda x: (x["period"] == "undated", x["period"]))
    labels = [r["period"] for r in rows]
    detected = [int(r["detected"]) for r in rows]
    resolved = [int(r["resolved"]) for r in rows]
    open_n = [int(r["open"]) for r in rows]
    cumulative = []
    acc = 0
    for d in detected:
        acc += d
        cumulative.append(acc)
    return {
        "run_id": run_id,
        "labels": labels,
        "detected": detected,
        "resolved": resolved,
        "open": open_n,
        "cumulative": cumulative,
    }


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
