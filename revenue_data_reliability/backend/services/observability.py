"""Observability queries for the /observability route (SPEC §13).

Reads the OTEL tables written by the custom Postgres exporter and builds
a trace list, a span tree, and the logs linked to one trace.
"""

import json
from datetime import datetime

from backend.db.connection import fetch_all, fetch_one


def _fmt_dt(value):
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def _fmt_duration(start, end) -> str:
    if not start or not end:
        return "-"
    delta = (end - start).total_seconds()
    if delta < 1:
        return f"{delta * 1000:.1f}ms"
    return f"{delta:.2f}s"


def list_traces(limit: int = 25) -> list[dict]:
    """One row per trace: root span name, span count, duration, status."""
    rows = fetch_all(
        """
        SELECT
            trace_id,
            COALESCE(
                (ARRAY_AGG(name ORDER BY start_time ASC NULLS LAST) FILTER (WHERE parent_span_id IS NULL))[1],
                (ARRAY_AGG(name ORDER BY start_time ASC NULLS LAST))[1]
            ) AS root_name,
            COUNT(*) AS span_count,
            MIN(start_time) AS started_at,
            MAX(end_time) AS ended_at,
            BOOL_OR(status = 'ERROR') AS has_error
        FROM otel_spans
        GROUP BY trace_id
        ORDER BY MAX(start_time) DESC NULLS LAST
        LIMIT %s
        """,
        (limit,),
    )
    out = []
    for r in rows:
        out.append(
            {
                "trace_id": r["trace_id"],
                "name": r["root_name"],
                "duration": _fmt_duration(r["started_at"], r["ended_at"]),
                "status": "error" if r["has_error"] else "ok",
                "spans": r["span_count"],
                "started_at": _fmt_dt(r["started_at"]),
            }
        )
    return out


def get_span_tree(trace_id: str) -> list[dict]:
    """Spans for one trace, depth-sorted with depth, offset and service."""
    rows = fetch_all(
        """
        SELECT span_id, trace_id, parent_span_id, name, start_time, end_time,
               duration_ms, status, attributes, created_at
        FROM otel_spans
        WHERE trace_id = %s
        ORDER BY start_time ASC NULLS LAST, span_id
        """,
        (trace_id,),
    )
    by_id = {r["span_id"]: r for r in rows}
    root_start = min(
        (r["start_time"] for r in rows if r["start_time"]), default=None
    )

    def depth_of(row: dict, seen: set | None = None) -> int:
        seen = seen or set()
        if row["span_id"] in seen or not row["parent_span_id"]:
            return 0
        seen.add(row["span_id"])
        parent = by_id.get(row["parent_span_id"])
        return (depth_of(parent, seen) + 1) if parent else 0

    out = []
    for r in rows:
        attrs = r.get("attributes")
        if isinstance(attrs, str):
            try:
                attrs = json.loads(attrs)
            except (TypeError, ValueError):
                attrs = {}
        attrs = attrs if isinstance(attrs, dict) else {}
        duration_ms = float(r["duration_ms"] or 0.0)
        offset_ms = 0.0
        if root_start and r["start_time"]:
            offset_ms = (r["start_time"] - root_start).total_seconds() * 1000
        out.append(
            {
                "span_id": r["span_id"],
                "name": r["name"],
                "duration": (
                    f"{duration_ms:.1f}ms" if r["duration_ms"] is not None else "-"
                ),
                "duration_ms": round(duration_ms, 2),
                "offset_ms": round(offset_ms, 2),
                "status": r["status"].lower() if r["status"] else "unset",
                "depth": depth_of(r),
                "service": (
                    attrs.get("otel.scope.name")
                    or attrs.get("service.name")
                    or "unknown"
                ),
                "started_at": _fmt_dt(r["start_time"]),
            }
        )
    return out


def latency_series(hours: int = 24) -> dict:
    """Hourly p50/p95 span latency for the recent window."""
    rows = fetch_all(
        """
        SELECT date_trunc('hour', start_time) AS bucket,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY duration_ms) AS p50,
               percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms) AS p95
        FROM otel_spans
        WHERE start_time >= now() - (%s * interval '1 hour')
          AND duration_ms IS NOT NULL
        GROUP BY 1
        ORDER BY 1
        """,
        (hours,),
    )
    return {
        "labels": [r["bucket"].strftime("%H:00") for r in rows if r["bucket"]],
        "p50": [round(float(r["p50"] or 0), 2) for r in rows],
        "p95": [round(float(r["p95"] or 0), 2) for r in rows],
    }


def spans_by_service(hours: int = 24) -> list[dict]:
    """Span counts grouped by instrumentation/service scope."""
    rows = fetch_all(
        """
        SELECT COALESCE(
                   attributes->>'otel.scope.name',
                   attributes->>'service.name',
                   'unknown'
               ) AS service,
               COUNT(*) AS spans
        FROM otel_spans
        WHERE start_time >= now() - (%s * interval '1 hour')
        GROUP BY 1
        ORDER BY spans DESC
        """,
        (hours,),
    )
    names = {
        "fastapi": "FastAPI",
        "psycopg": "PostgreSQL",
        "botocore": "AWS SDK",
        "duckdb": "DuckDB",
        "controller": "Scheduler",
    }
    out = []
    for r in rows:
        raw = str(r["service"] or "unknown")
        key = raw.split(".")[-1].lower()
        out.append(
            {
                "service": names.get(key, raw.replace("_", " ").title()),
                "spans": int(r["spans"] or 0),
            }
        )
    return out


def get_trace_logs(trace_id: str) -> list[dict]:
    """Log records linked (by trace_id) to one trace."""
    rows = fetch_all(
        """
        SELECT log_id, trace_id, span_id, level, message, attributes, created_at
        FROM otel_logs
        WHERE trace_id = %s
        ORDER BY created_at ASC, log_id ASC
        """,
        (trace_id,),
    )
    out = []
    for r in rows:
        attrs = r.get("attributes")
        if isinstance(attrs, str):
            try:
                attrs = json.loads(attrs)
            except Exception:
                pass
        out.append(
            {
                "level": r["level"],
                "message": r["message"],
                "attributes": attrs,
                "created_at": _fmt_dt(r["created_at"]),
            }
        )
    return out


def telemetry_summary() -> dict:
    """Counts and retention window for the page header."""
    counts = fetch_one(
        """
        SELECT
            (SELECT COUNT(DISTINCT trace_id) FROM otel_spans) AS trace_count,
            (SELECT COUNT(*) FROM otel_spans) AS span_count,
            (SELECT COUNT(*) FROM otel_logs) AS log_count
        """
    )
    return counts or {"trace_count": 0, "span_count": 0, "log_count": 0}
