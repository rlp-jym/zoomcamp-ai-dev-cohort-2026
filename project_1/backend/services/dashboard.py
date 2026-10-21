"""Dashboard service (SPEC §19, §3): real KPIs and chart data.

Every number comes from the published dataset — the published run's
invoice_lines read through ``get_published_data_query`` (quarantine overlay
applied) — plus cheap Postgres counters for process/reliability KPIs.

The S3 Parquet scan runs ONLY inside ``refresh_dashboard_cache`` (called by
an APScheduler job / an explicit user refresh), never inside a request: the
``/`` route reads the precomputed payload from the ``dashboard_cache``
table, so page loads stay fast and stay out of long-running request paths.
"""

import json
import logging
import time
from datetime import datetime

from backend.config import settings
from backend.db.connection import execute, fetch_all, fetch_one
from backend.services import alerts as alerts_svc
from backend.services import messages as msg_svc
from backend.services import publications as pub_svc

logger = logging.getLogger(__name__)

SCENARIO = "baseline_run"

# Segments the source system recognises. A segment outside this set is a
# mapping drift (a value that no longer exists upstream) and is surfaced as
# an anomaly instead of being blended into the normal business mix.
KNOWN_SEGMENTS = ("enterprise", "midmarket", "smb")
SEGMENT_COLORS = {
    "known": ("#1f2a44", "#4a6fa5", "#9aa0a6"),
    "anomaly": "#cf222e",
}

# Short-lived in-memory cache for the request-path dashboard payload.
_DASHBOARD_CACHE: dict = {"payload": None, "ts": 0.0}
_DASHBOARD_CACHE_TTL = 5.0


def invalidate_dashboard_cache() -> None:
    _DASHBOARD_CACHE["payload"] = None
    _DASHBOARD_CACHE["ts"] = 0.0


def _uri(scenario: str, table: str) -> str:
    return f"s3://{settings.r2_bucket}/scenarios/{scenario}/{table}.parquet"


def _shift_month(ym: str, months: int) -> str:
    """Shift a ``YYYY-MM`` key forward by ``months`` (e.g. 2026-12 -> 2027-01)."""
    year, month = (int(p) for p in ym.split("-"))
    total = year * 12 + (month - 1) + months
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def _fmt_m(value) -> str:
    """$4.21M style formatting."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "n/a"
    return f"${value / 1_000_000:.2f}M"


def _fmt_pct(value) -> str:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "n/a"
    return f"{value:.1f}%"


def _pct_delta(current, previous) -> str | None:
    try:
        current, previous = float(current), float(previous)
    except (TypeError, ValueError):
        return None
    if previous == 0:
        return None
    return f"{(current - previous) / previous * 100:+.1f}%"


def get_dashboard_data(scenario: str = SCENARIO) -> dict:
    """All dashboard payload: open-exceptions stat, 3 charts, attainment card, alert badge."""
    from backend.storage.duckdb_client import query_rows

    q = pub_svc.get_published_data_query(scenario)
    data = {
        "scenario": scenario,
        "published_run": q["run_id"] if q else None,
        "available": bool(q),
        "alerts": alerts_svc.open_alerts(),
        "alert_count": alerts_svc.open_alert_count(),
        "kpis": [],
        "charts": {},
    }

    # Open exceptions are the one KPI we keep on the dashboard: a reminder
    # that the current numbers still have pending exceptions to fix. The
    # other KPIs (Revenue/Billings/GL Variance/DQ Pass Rate/Published Runs)
    # are snapshots with no discussion value and were removed in favour of
    # the charts + their threads.
    exc_row = fetch_one(
        """
        SELECT COUNT(*) FILTER (WHERE status <> 'resolved') AS open_n,
               COUNT(*) AS total
        FROM exceptions
        """
    )
    data["open_exceptions"] = exc_row["open_n"] if exc_row else 0

    if not q:
        # No publication yet — keep the open-exceptions reminder only.
        data["charts"] = {}
        data["attainment"] = None
        return data

    pubsql = q["sql"]

    # ---- one materialized scan of the published invoice lines -------------
    rows_a = query_rows(f"""
        WITH inv AS (
            SELECT invoice_id, customer_id,
                   strftime(invoice_date, '%Y-%m') AS ym
            FROM read_parquet('{_uri(scenario, "invoices")}')
        ),
        bil AS MATERIALIZED ({pubsql})
        SELECT 'billings_total' AS kind, '' AS label, '' AS ym,
               COALESCE(SUM(line_subtotal), 0) AS amt
            FROM bil
        UNION ALL
        SELECT 'billings_month', '', CAST(i.ym AS VARCHAR),
               SUM(bil.line_subtotal)
            FROM bil
            JOIN inv i ON bil.invoice_id = i.invoice_id
            GROUP BY 3
        UNION ALL
        SELECT 'segment', COALESCE(c.segment, 'Unknown'), '',
               SUM(bil.line_subtotal)
            FROM bil
            JOIN inv i ON bil.invoice_id = i.invoice_id
            JOIN read_parquet('{_uri(scenario, "customers")}') c
                 ON i.customer_id = c.customer_id
            GROUP BY 2
    """)

    billings_month = {
        r["ym"]: float(r["amt"]) for r in rows_a if r["kind"] == "billings_month"
        and r["ym"]
    }
    segments = [
        {"label": r["label"], "amount": float(r["amt"])}
        for r in rows_a if r["kind"] == "segment"
    ]
    segments.sort(key=lambda s: -s["amount"])
    billings_total = next(
        (float(r["amt"]) for r in rows_a if r["kind"] == "billings_total"), 0.0
    )

    # ---- small monthly tables: General Ledger revenue and budget ------------
    # A restatement supersedes the row it restates, so only the highest
    # version per (period, account_id, item_category) counts as current GL.
    gl_month = {
        r["period"]: float(r["amt"])
        for r in query_rows(
            f"""
            SELECT period, SUM(recognized_revenue_amt) AS amt
            FROM (
                SELECT period, account_id, item_category, recognized_revenue_amt,
                       ROW_NUMBER() OVER (
                           PARTITION BY period, account_id, item_category
                           ORDER BY version DESC
                       ) AS rn
                FROM read_parquet('{_uri(scenario, "gl_revenue")}')
            )
            WHERE rn = 1
            GROUP BY 1
            """
        )
    }
    budget_month = {
        r["ym"]: float(r["amt"])
        for r in query_rows(f"""
            SELECT strftime(CAST(period AS DATE), '%Y-%m') AS ym,
                   SUM(budget_revenue_amt) AS amt
            FROM read_parquet('{_uri(scenario, "budget")}')
            GROUP BY 1
            """
        )
    }

    # Exclude partial tail months (e.g. a 580-invoice ghost month) from the
    # chart window, consistent with the MTD filter below.
    max_monthly = max(billings_month.values() or [0.0])
    full_months = sorted(
        m for m, a in billings_month.items() if not max_monthly or a >= 0.5 * max_monthly
    )
    months = sorted(
        m for m in (set(gl_month) | set(billings_month) | set(budget_month))
        if m in set(full_months)
    )[-6:]

    gl_total = sum(gl_month.values())
    gl_variance_pct = (
        (billings_total - gl_total) / gl_total * 100 if gl_total else 0.0
    )

    # "MTD" = latest full month of activity — the calendar tail month can be
    # a partial ingest, which would zero the headline numbers.
    mtd_key = full_months[-1] if full_months else (months[-1] if months else None)
    gl_mtd = gl_month.get(mtd_key, 0.0) if mtd_key else 0.0
    billings_mtd = billings_month.get(mtd_key, 0.0) if mtd_key else 0.0
    prev_mtd_key = (
        full_months[-2] if len(full_months) > 1
        else (months[-2] if len(months) > 1 else None)
    )
    gl_prev = gl_month.get(prev_mtd_key, 0.0) if prev_mtd_key else 0.0
    bill_prev = billings_month.get(prev_mtd_key, 0.0) if prev_mtd_key else 0.0

    # KPI cards removed in favour of charts + their threads; the
    # open-exceptions count survives as a threadless stat strip.
    data["kpis"] = []

    variance_rows = fetch_all(
        """
        SELECT item_category, AVG(variance_pct) * 100 AS avg_var, COUNT(*) AS n
        FROM reconciliations
        WHERE run_id = %s
        GROUP BY item_category
        ORDER BY ABS(AVG(variance_pct)) DESC
        LIMIT 5
        """,
        (q["run_id"],),
    )

    # ---- growth, run-rate projection and budget attainment ----------------
    gl_values = [gl_month.get(m, 0.0) for m in months]
    growth_rates = [
        round((gl_values[i] - gl_values[i - 1]) / gl_values[i - 1] * 100, 1)
        if gl_values[i - 1] > 0 else None
        for i in range(1, len(gl_values))
    ]

    # Run-rate projection: carry the average growth of the last three
    # months forward for three months. It is an extension of the actual
    # series, so it is drawn on the same chart rather than as its own card.
    last3 = gl_values[-3:] if len(gl_values) >= 3 else gl_values
    recent = [
        (last3[i] - last3[i - 1]) / last3[i - 1]
        for i in range(1, len(last3))
        if last3[i - 1] != 0
    ]
    avg_growth = sum(recent) / len(recent) if recent else 0.0
    projected = [
        gl_values[-1] * (1 + avg_growth) ** i for i in range(1, 4)
    ] if gl_values else []

    projection_labels = (
        [_shift_month(months[-1], i) for i in (1, 2, 3)] if months else []
    )
    chart_labels = months + projection_labels
    tail = [None] * len(projection_labels)

    budget_total = sum(budget_month.get(m, 0.0) for m in months)
    attainment_pct = (
        round(sum(gl_values) / budget_total * 100, 1) if budget_total else None
    )

    # Segment mix for the attainment card. Unrecognised segments are kept
    # (and flagged) rather than dropped — they are the visible trace of a
    # customer-master mapping drift.
    seg_total = sum(s["amount"] for s in segments)
    segment_mix = []
    for idx, s in enumerate(segments[:6]):
        known = s["label"] in KNOWN_SEGMENTS
        segment_mix.append({
            "label": s["label"],
            "amount": s["amount"],
            "share": round(s["amount"] / seg_total * 100, 2) if seg_total else 0.0,
            "known": known,
            "color": (
                SEGMENT_COLORS["anomaly"] if not known
                else SEGMENT_COLORS["known"][idx % len(SEGMENT_COLORS["known"])]
            ),
        })

    data["charts"] = {
        # One chart carries actuals, plan and the run-rate projection: the
        # General Ledger series used to be drawn twice (once against
        # budget, once against billings) and the projection lived in its
        # own card, so the same numbers were on screen three times.
        "revenue_plan": {
            "labels": chart_labels,
            "actual": [
                round(gl_month.get(m, 0.0) / 1e6, 3) for m in months
            ] + tail,
            "billings": [
                round(billings_month.get(m, 0.0) / 1e6, 3) for m in months
            ] + tail,
            "budget": [
                round(budget_month[m] / 1e6, 3)
                if budget_month.get(m) is not None else None
                for m in chart_labels
            ],
            # Anchored on the last actual month so the dashed line joins
            # the actual series instead of floating beside it.
            "projection": (
                [None] * (len(months) - 1)
                + [round(gl_values[-1] / 1e6, 3)]
                + [round(p / 1e6, 3) for p in projected]
            ) if gl_values else [],
            "avg_growth_pct": round(avg_growth * 100, 1),
        },
        "variance_category": {
            "labels": [r["item_category"] for r in variance_rows],
            "values": [round(float(r["avg_var"] or 0), 4) for r in variance_rows],
        },
        "growth": {
            "labels": months[1:],
            "values": growth_rates,
        },
        "segment_mix": segment_mix,
    }
    data["attainment"] = {
        "pct": attainment_pct,
        "months": len(months),
    }
    return data


def refresh_dashboard_cache(scenario: str = SCENARIO) -> str:
    """Recompute the payload (S3 scans) and upsert it into dashboard_cache.

    Called by the scheduler job — never in the request path.
    Returns 'updated' | 'empty' | 'error: ...'.
    """
    try:
        data = get_dashboard_data(scenario)
    except Exception as exc:
        logger.exception("Dashboard cache refresh failed.")
        return f"error: {exc}"
    if not data.get("available"):
        logger.info("Dashboard: no published dataset — cache left empty.")
        return "empty"
    execute(
        """
        INSERT INTO dashboard_cache (cache_key, data, refreshed_at)
        VALUES (%s, %s, now())
        ON CONFLICT (cache_key) DO UPDATE
            SET data = EXCLUDED.data, refreshed_at = now()
        """,
        ("dashboard", json.dumps(data, default=str)),
    )
    invalidate_dashboard_cache()
    return "updated"


def get_from_cache(cache_key: str = "dashboard") -> tuple[dict | None, datetime | None]:
    """Read the cached payload (returns None when never computed)."""
    row = fetch_one(
        "SELECT data, refreshed_at FROM dashboard_cache WHERE cache_key = %s",
        (cache_key,),
    )
    if not row:
        return None, None
    payload = row["data"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return payload, row["refreshed_at"]


def get_dashboard_data_cached(scenario: str = SCENARIO) -> dict:
    """Request-path wrapper: reads the cache only, never scans S3."""
    now = time.time()
    cached = _DASHBOARD_CACHE["payload"]
    if cached is not None and now - _DASHBOARD_CACHE["ts"] < _DASHBOARD_CACHE_TTL:
        return cached

    data, refreshed_at = get_from_cache()
    if data is None:
        result = {
            "scenario": scenario,
            "published_run": None,
            "available": False,
            "alerts": alerts_svc.open_alerts(),
            "alert_count": alerts_svc.open_alert_count(),
            "kpis": [],
            "charts": {},
            "open_exceptions": 0,
            "chart_messages": {},
            "cache_fresh_at": None,
            "cache_empty": True,
        }
        _DASHBOARD_CACHE["payload"] = result
        _DASHBOARD_CACHE["ts"] = time.time()
        return result
    data["cache_empty"] = False
    # Cheap Postgres values are re-read live on every request so the badge
    # and analysis threads never lag behind the parquet snapshot.
    alerts, alert_count = alerts_svc.open_alerts_with_count()
    data["alerts"] = alerts
    data["alert_count"] = alert_count
    # Chart discussion threads (one per chart card).
    chart_thread_ids = [
        "chart-revenue-plan", "chart-variance-category",
        "chart-growth", "chart-attainment",
    ]
    msgs_by_thread = msg_svc.get_messages_for_threads("analysis", chart_thread_ids)
    data["chart_messages"] = {
        aid: msgs_by_thread.get(aid, []) for aid in chart_thread_ids
    }
    # Keep open_exceptions fresh from Postgres.
    exc_row = fetch_one(
        "SELECT COUNT(*) FILTER (WHERE status <> 'resolved') AS open_n FROM exceptions"
    )
    data["open_exceptions"] = exc_row["open_n"] if exc_row else 0
    data["kpi_cache"] = {
        "refreshed_at": refreshed_at.strftime("%Y-%m-%d %I:%M:%S %p") if refreshed_at else "",
    }
    _DASHBOARD_CACHE["payload"] = data
    _DASHBOARD_CACHE["ts"] = time.time()
    return data
