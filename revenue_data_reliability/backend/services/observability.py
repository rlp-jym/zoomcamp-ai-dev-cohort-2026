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


def _fmt_display_dt(value) -> str:
    """Format a timestamp as ``Oct 24, 2026, 4:03 PM``."""
    if value is None:
        return "—"
    if isinstance(value, datetime):
        hour = value.strftime("%I:%M %p").lstrip("0")
        return f"{value.strftime('%b')} {value.day}, {value.year}, {hour}"
    return str(value)


def _trace_context(name: str) -> str:
    mapping = {
        "pipeline.run": "Pipeline Run",
        "controller.verification_job": "Controller Verification",
        "controller_verification_job": "Controller Verification",
    }
    return mapping.get(name, name or "Unknown")


def _trace_action(name: str, attributes) -> str:
    attrs = attributes
    if isinstance(attrs, str):
        try:
            attrs = json.loads(attrs)
        except (TypeError, ValueError):
            attrs = {}
    attrs = attrs if isinstance(attrs, dict) else {}
    if name == "pipeline.run":
        run_id = attrs.get("run.id") or attrs.get("run_id")
        return f"Run #{run_id}" if run_id else "Pipeline Run"
    if "controller" in (name or "").lower():
        return "Controller Verification"
    if (name or "").startswith(
        ("GET ", "POST ", "PUT ", "PATCH ", "DELETE ", "OPTIONS ")
    ):
        return "HTTP Request"
    return "Isolated span"


def list_traces(limit: int = 25) -> list[dict]:
    """Root spans only, excluding health checks/static assets and DB noise.

    Slowest traces sort first, matching standard APM behavior.
    """
    rows = fetch_all(
        """
        SELECT s.trace_id, s.name, s.start_time,
               s.start_time + (COALESCE(s.duration_ms, 0) * interval '1 millisecond') AS ended_at,
               s.duration_ms, s.status, s.attributes,
               (SELECT COUNT(*) FROM otel_spans c
                WHERE c.trace_id = s.trace_id) AS span_count,
               CASE
                   WHEN s.name = 'pipeline.run' THEN COALESCE(
                       (SELECT r.triggered_by FROM runs r
                        WHERE r.trace_id = s.trace_id
                        ORDER BY r.run_id DESC LIMIT 1), 'system')
                   WHEN s.name ILIKE '%%controller%%' THEN 'controller'
                   ELSE COALESCE(
                       (SELECT a.persona_id FROM approvals a
                        WHERE a.trace_id = s.trace_id
                        ORDER BY a.created_at DESC NULLS LAST LIMIT 1),
                       (SELECT aa.agent_id FROM agent_actions aa
                        WHERE aa.trace_id = s.trace_id
                        ORDER BY aa.created_at DESC NULLS LAST LIMIT 1),
                       (SELECT m.persona_id FROM messages m
                        WHERE m.trace_id = s.trace_id
                        ORDER BY m.created_at DESC NULLS LAST LIMIT 1),
                       (SELECT r.triggered_by FROM runs r
                        WHERE r.trace_id = s.trace_id
                        ORDER BY r.run_id DESC LIMIT 1),
                       'system'
                   )
               END AS actor
        FROM otel_spans s
        WHERE s.parent_span_id IS NULL
          AND COALESCE(s.name, '') NOT LIKE '%%/static%%'
          AND COALESCE(s.name, '') NOT ILIKE 'HEAD /%%'
          AND COALESCE(s.name, '') NOT LIKE '%%/health%%'
          AND COALESCE(s.name, '') <> 'duckdb.query'
        ORDER BY s.start_time DESC NULLS LAST,
                 s.duration_ms DESC NULLS LAST
        LIMIT %s
        """,
        (limit,),
    )
    out = []
    for r in rows:
        out.append(
            {
                "trace_id": r["trace_id"],
                "name": r["name"],
                "context": _trace_context(r["name"]),
                "action": _trace_action(r["name"], r["attributes"]),
                "duration": _fmt_duration(r["start_time"], r["ended_at"]),
                "duration_ms": round(float(r["duration_ms"] or 0.0), 2),
                "status": "error" if r["status"] == "ERROR" else "ok",
                "spans": r["span_count"],
                "actor": r["actor"] or "system",
                "started_at": _fmt_display_dt(r["start_time"]),
                "started_sort": _fmt_dt(r["start_time"]),
                "ended_at": _fmt_display_dt(r["ended_at"]),
            }
        )
    return out


def get_trace_name(trace_id: str) -> str:
    """Resolve a trace's root span name for the detail header."""
    row = fetch_one(
        """
        SELECT name FROM otel_spans
        WHERE trace_id = %s
        ORDER BY (parent_span_id IS NULL) DESC, start_time ASC NULLS LAST
        LIMIT 1
        """,
        (trace_id,),
    )
    return row["name"] if row else "Unknown"


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
               COUNT(*) AS spans,
               COALESCE(SUM(duration_ms), 0) AS duration_ms
        FROM otel_spans
        WHERE start_time >= now() - (%s * interval '1 hour')
        GROUP BY 1
        ORDER BY duration_ms DESC
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
                "duration_ms": round(float(r["duration_ms"] or 0), 2),
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
