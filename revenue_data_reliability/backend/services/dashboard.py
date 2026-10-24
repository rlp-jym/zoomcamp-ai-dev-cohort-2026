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
import threading
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

# Short-lived in-memory cache for the request-path dashboard payload, keyed by
# scenario (dataset) so switching datasets never reuses another dataset's data.
_DASHBOARD_CACHE: dict = {}
_DASHBOARD_CACHE_TTL = 5.0
_DASHBOARD_REFRESHING: set = set()
_DASHBOARD_REFRESH_LOCK = threading.Lock()


def invalidate_dashboard_cache(scenario=None) -> None:
    if scenario is None:
        _DASHBOARD_CACHE.clear()
    else:
        _DASHBOARD_CACHE.pop(scenario, None)


def invalidate_all_dashboard_cache() -> None:
    """Drop every cached row (DB + memory). Used by scheduler/reset."""
    _DASHBOARD_CACHE.clear()
    try:
        from backend.db.connection import execute

        execute("DELETE FROM dashboard_cache")
    except Exception:
        pass


def _uri(scenario: str, table: str) -> str:
    from backend.storage.s3_client import resolve_data_scenario

    source = resolve_data_scenario(scenario)
    return f"s3://{settings.r2_bucket}/scenarios/{source}/{table}.parquet"


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
        "dataset": scenario,
        "dataset_name": scenario,
        "scenario": scenario,
        "published_run": q["run_id"] if q else None,
        "available": bool(q),
        "alerts": alerts_svc.open_alerts(),
        "alert_count": alerts_svc.open_alert_count(),
        "kpis": [],
        "charts": {},
    }

    if not q:
        # No publication yet — keep the empty payload the template needs.
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
    (
        (billings_total - gl_total) / gl_total * 100 if gl_total else 0.0
    )

    # "MTD" = latest full month of activity — the calendar tail month can be
    # a partial ingest, which would zero the headline numbers.
    mtd_key = full_months[-1] if full_months else (months[-1] if months else None)
    gl_month.get(mtd_key, 0.0) if mtd_key else 0.0
    billings_month.get(mtd_key, 0.0) if mtd_key else 0.0
    prev_mtd_key = (
        full_months[-2] if len(full_months) > 1
        else (months[-2] if len(months) > 1 else None)
    )
    gl_month.get(prev_mtd_key, 0.0) if prev_mtd_key else 0.0
    billings_month.get(prev_mtd_key, 0.0) if prev_mtd_key else 0.0

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

    # ---- growth and target attainment ---------------------------------------
    gl_values = [gl_month.get(m, 0.0) for m in months]
    growth_rates = [
        round((gl_values[i] - gl_values[i - 1]) / gl_values[i - 1] * 100, 1)
        if gl_values[i - 1] > 0 else None
        for i in range(1, len(gl_values))
    ]

    budget_total = sum(budget_month.get(m, 0.0) for m in months)
    attainment_pct = (
        round(sum(gl_values) / budget_total * 100, 1) if budget_total else None
    )

    # Segment mix for the segment card. Unrecognised segments are kept
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
        # One chart carries actuals, billings and target: the General
        # Ledger series used to be drawn twice (once against budget, once
        # against billings). Forward-looking projections now live under
        # Scenarios, not on this actuals page.
        "revenue_plan": {
            "labels": months,
            "actual": [
                round(gl_month.get(m, 0.0) / 1e6, 3) for m in months
            ],
            "billings": [
                round(billings_month.get(m, 0.0) / 1e6, 3) for m in months
            ],
            "budget": [
                round(budget_month[m] / 1e6, 3)
                if budget_month.get(m) is not None else None
                for m in months
            ],
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
        "latest": months[-1] if months else None,
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
        INSERT INTO dashboard_cache (cache_key, dataset_name, data, refreshed_at)
        VALUES (%s, %s, %s, now())
        ON CONFLICT (dataset_name) DO UPDATE
            SET cache_key = EXCLUDED.cache_key,
                data = EXCLUDED.data,
                refreshed_at = now()
        """,
        (f"dashboard:{scenario}", scenario, json.dumps(data, default=str)),
    )
    invalidate_dashboard_cache(scenario)
    return "updated"


def get_from_cache(scenario: str = SCENARIO) -> tuple[dict | None, datetime | None]:
    """Read the cached payload for a scenario (returns None when never computed)."""
    row = fetch_one(
        "SELECT data, refreshed_at FROM dashboard_cache WHERE dataset_name = %s",
        (scenario,),
    )
    if not row:
        row = fetch_one(
            "SELECT data, refreshed_at FROM dashboard_cache WHERE cache_key = %s",
            (scenario,),
        )
    if not row:
        return None, None
    payload = row["data"]
    if isinstance(payload, str):
        payload = json.loads(payload)
    return payload, row["refreshed_at"]


def _background_refresh(scenario: str) -> None:
    try:
        refresh_dashboard_cache(scenario)
    except Exception:
        logger.exception("Background dashboard refresh failed for %s", scenario)
    finally:
        with _DASHBOARD_REFRESH_LOCK:
            _DASHBOARD_REFRESHING.discard(scenario)


def get_dashboard_data_cached(scenario: str = SCENARIO) -> dict:
    """Request-path wrapper: reads the cache only, never scans S3.

    On a cache miss a background refresh is triggered (lazy) so the request
    thread never pays the S3/DuckDB cost.
    """
    now = time.time()
    cached = _DASHBOARD_CACHE.get(scenario)
    if cached is not None and now - cached["ts"] < _DASHBOARD_CACHE_TTL:
        return cached["payload"]

    data, refreshed_at = get_from_cache(scenario)
    if data is None:
        with _DASHBOARD_REFRESH_LOCK:
            if scenario not in _DASHBOARD_REFRESHING:
                _DASHBOARD_REFRESHING.add(scenario)
                threading.Thread(
                    target=_background_refresh, args=(scenario,), daemon=True
                ).start()
        result = {
            "dataset": scenario,
            "dataset_name": scenario,
            "scenario": scenario,
            "published_run": None,
            "available": False,
            "alerts": alerts_svc.open_alerts(),
            "alert_count": alerts_svc.open_alert_count(),
            "kpis": [],
            "charts": {},
            "chart_messages": {},
            "cache_fresh_at": None,
            "cache_empty": True,
        }
        _DASHBOARD_CACHE[scenario] = {"payload": result, "ts": now}
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
        "chart-growth", "chart-segment",
    ]
    msgs_by_thread = msg_svc.get_messages_for_threads("analysis", chart_thread_ids)
    data["chart_messages"] = {
        aid: msgs_by_thread.get(aid, []) for aid in chart_thread_ids
    }
    data["kpi_cache"] = {
        "refreshed_at": refreshed_at.strftime("%Y-%m-%d %I:%M:%S %p") if refreshed_at else "",
    }
    _DASHBOARD_CACHE[scenario] = {"payload": data, "ts": now}
    return data
