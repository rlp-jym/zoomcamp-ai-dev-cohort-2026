"""Alert service (SPEC §12): six in-app alert types with 1-hour dedup.

Destinations on a fresh alert:
1. one ``alerts`` row,
2. a Controller triage message on the anchor thread.

Dedup: ``(alert_type, anchor_id)`` inside the dedup window (1 hour) yields
None — no new row and no new thread message.
"""

from backend.db.connection import execute, fetch_all, fetch_one

SEVERITIES = {
    "STALE_PUBLISHED": "high",
    "SOURCE_HASH_MISMATCH": "critical",
    "AUDIT_ROW_MISSING": "high",
    "THREAD_ANCHOR_ORPHANED": "medium",
    "PUBLISHED_RECORD_FAILS_REVALIDATION": "critical",
    "RECON_DRIFT": "critical",
}

DEDUP_WINDOW_MINUTES = 60


def _dedup_hit(alert_type: str, anchor_id: str) -> dict | None:
    """An open alert for the same (type, anchor) inside the dedup window."""
    return fetch_one(
        """
        SELECT alert_id, created_at FROM alerts
        WHERE alert_type = %s AND anchor_id = %s
          AND created_at > now() - (%s * interval '1 minute')
        ORDER BY alert_id DESC
        LIMIT 1
        """,
        (alert_type, str(anchor_id), DEDUP_WINDOW_MINUTES),
    )


def raise_alert(
    alert_type: str,
    anchor_type: str | None,
    anchor_id: str,
    detail: str,
    trace_id: str | None = None,
    severity: str | None = None,
) -> dict:
    """Create one alert (deduplicated). Returns {created, alert_id, severity}."""
    severity = severity or SEVERITIES.get(alert_type, "medium")
    existing = _dedup_hit(alert_type, anchor_id)
    if existing:
        return {"created": False, "alert_id": existing["alert_id"], "severity": severity}

    row = fetch_one(
        """
        INSERT INTO alerts (alert_type, anchor_type, anchor_id, severity, status, trace_id)
        VALUES (%s, %s, %s, %s, 'open', %s)
        RETURNING alert_id, created_at
        """,
        (alert_type, anchor_type, str(anchor_id), severity, trace_id),
    )
    try:
        from backend.services import dashboard as _dashboard_svc

        _dashboard_svc.invalidate_dashboard_cache()
    except Exception:
        pass
    return {"created": True, "alert_id": row["alert_id"], "severity": severity}


def open_alerts(limit: int = 5) -> list[dict]:
    """Open alerts for the dashboard badge."""
    rows = fetch_all(
        """
        SELECT alert_id, alert_type, anchor_type, anchor_id, severity, status,
               trace_id, created_at
        FROM alerts WHERE status = 'open'
        ORDER BY alert_id DESC
        LIMIT %s
        """,
        (limit,),
    )
    return [
        {
            "id": r["alert_id"],
            "alert_type": r["alert_type"],
            "anchor_type": r["anchor_type"],
            "anchor_id": r["anchor_id"],
            "severity": r["severity"],
            "created_at": r["created_at"].strftime("%Y-%m-%d %H:%M") if r["created_at"] else "",
        }
        for r in rows
    ]


def open_alert_count() -> int:
    row = fetch_one("SELECT COUNT(*) AS n FROM alerts WHERE status = 'open'")
    return row["n"]


def open_alerts_with_count(limit: int = 5) -> tuple[list[dict], int]:
    """Fetch open alerts and their total count in a single query."""
    rows = fetch_all(
        """
        SELECT alert_id, alert_type, anchor_type, anchor_id, severity, status,
               trace_id, created_at,
               (SELECT COUNT(*) FROM alerts WHERE status = 'open') AS total_count
        FROM alerts
        WHERE status = 'open'
        ORDER BY alert_id DESC
        LIMIT %s
        """,
        (limit,),
    )
    mapped = [
        {
            "id": r["alert_id"],
            "alert_type": r["alert_type"],
            "anchor_type": r["anchor_type"],
            "anchor_id": r["anchor_id"],
            "severity": r["severity"],
            "created_at": r["created_at"].strftime("%Y-%m-%d %H:%M") if r["created_at"] else "",
        }
        for r in rows
    ]
    count = rows[0]["total_count"] if rows else 0
    return mapped, count


def resolve_alert(alert_id: int) -> None:
    execute("UPDATE alerts SET status = 'resolved' WHERE alert_id = %s", (alert_id,))
