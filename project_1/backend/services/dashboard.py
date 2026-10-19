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

# Short-lived in-memory cache for the request-path dashboard payload.
_DASHBOARD_CACHE: dict = {"payload": None, "ts": 0.0}
_DASHBOARD_CACHE_TTL = 5.0


def invalidate_dashboard_cache() -> None:
    _DASHBOARD_CACHE["payload"] = None
    _DASHBOARD_CACHE["ts"] = 0.0


def _uri(scenario: str, table: str) -> str:
    return f"s3://{settings.r2_bucket}/scenarios/{scenario}/{table}.parquet"


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
    """All dashboard payload: 6 KPI cards, 4 charts, alert badge."""
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

    # Postgres-only KPIs (cheap, no S3 scan).
    exc_row = fetch_one(
        """
        SELECT COUNT(*) FILTER (WHERE status <> 'resolved') AS open_n,
               COUNT(*) AS total
        FROM exceptions
        """
    )
    run_rate = fetch_one(
        """
        SELECT 100.0 * SUM(CASE WHEN v.status = 'pass' THEN 1 ELSE 0 END)
                   / NULLIF(COUNT(*), 0) AS pass_rate,
               r.run_id
        FROM validations v
        JOIN runs r ON r.run_id = v.run_id
        WHERE r.status = 'completed'
        GROUP BY r.run_id
        ORDER BY r.run_id DESC
        LIMIT 1
        """
    )
    prev_rate = fetch_one(
        """
        SELECT 100.0 * SUM(CASE WHEN v.status = 'pass' THEN 1 ELSE 0 END)
                   / NULLIF(COUNT(*), 0) AS pass_rate
        FROM validations v
        JOIN runs r ON r.run_id = v.run_id
        WHERE r.status = 'completed' AND r.run_id < %s
        GROUP BY r.run_id
        ORDER BY r.run_id DESC
        LIMIT 1
        """,
        (run_rate["run_id"],),
    ) if run_rate else None
    pub_count = fetch_one(
        "SELECT COUNT(*) AS n FROM runs WHERE published = TRUE"
    )

    if not q:
        # No publication yet — show the process KPIs and an empty state.
        data["kpis"] = _process_kpis_only(run_rate, prev_rate, exc_row, pub_count)
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

    # ---- small monthly tables: GL revenue and budget ----------------------
    gl_month = {
        r["period"]: float(r["amt"])
        for r in query_rows(
            f"""
            SELECT period, SUM(recognized_revenue_amt) AS amt
            FROM read_parquet('{_uri(scenario, "gl_revenue")}')
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

    months = sorted(
        set(gl_month) | set(billings_month) | set(budget_month)
    )[-6:]

    gl_total = sum(gl_month.values())
    gl_variance_pct = (
        (billings_total - gl_total) / gl_total * 100 if gl_total else 0.0
    )

    # "MTD" = latest full month of activity — the calendar tail month can be
    # a partial ingest, which would zero the headline numbers.
    max_monthly = max(billings_month.values() or [0.0])
    full_months = sorted(
        m for m, a in billings_month.items() if not max_monthly or a >= 0.5 * max_monthly
    )
    mtd_key = full_months[-1] if full_months else (months[-1] if months else None)
    gl_mtd = gl_month.get(mtd_key, 0.0) if mtd_key else 0.0
    billings_mtd = billings_month.get(mtd_key, 0.0) if mtd_key else 0.0
    prev_mtd_key = (
        full_months[-2] if len(full_months) > 1
        else (months[-2] if len(months) > 1 else None)
    )
    gl_prev = gl_month.get(prev_mtd_key, 0.0) if prev_mtd_key else 0.0
    bill_prev = billings_month.get(prev_mtd_key, 0.0) if prev_mtd_key else 0.0

    kpis = [
        {
            "id": "revenue",
            "title": "Revenue (MTD)",
            "value": _fmt_m(gl_mtd),
            "delta": _pct_delta(gl_mtd, gl_prev),
            "trend": "up",
            "thread_id": "kpi-revenue",
        },
        {
            "id": "billings",
            "title": "Billings (MTD)",
            "value": _fmt_m(billings_mtd),
            "delta": _pct_delta(billings_mtd, bill_prev),
            "trend": "up",
            "thread_id": "kpi-billings",
        },
        {
            "id": "gl_variance",
            "title": "GL Variance %",
            "value": _fmt_pct(gl_variance_pct),
            "delta": "billings vs GL",
            "trend": "down",
            "thread_id": "kpi-gl-variance",
        },
    ]
    kpis += _process_kpis_only(run_rate, prev_rate, exc_row, pub_count)
    data["kpis"] = kpis
    for k in data["kpis"]:
        k["messages"] = msg_svc.get_messages("analysis", k["thread_id"])

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
    data["charts"] = {
        "revenue_budget": {
            "labels": months,
            "actual": [round(gl_month.get(m, 0.0) / 1e6, 3) for m in months],
            "budget": [
                round(budget_month.get(m, 0.0) / 1e6, 3) if budget_month.get(m) is not None
                else None
                for m in months
            ],
        },
        "variance_category": {
            "labels": [r["item_category"] for r in variance_rows],
            "values": [round(float(r["avg_var"] or 0), 4) for r in variance_rows],
        },
        "segments": {
            "labels": [s["label"] for s in segments[:5]],
            "values": [
                round(s["amount"] / 1e6, 3) for s in segments[:5]
            ],
        },
        "kpi_trend": {
            "labels": months,
            "billings": [
                round(billings_month.get(m, 0.0) / 1e6, 3) for m in months
            ],
            "gl": [round(gl_month.get(m, 0.0) / 1e6, 3) for m in months],
        },
        "billings_mtd": _fmt_m(billings_mtd),
    }
    data["fpa"] = _compute_fpa_outputs(
        scenario, months, gl_month, budget_month, segments, billings_month, _uri
    )
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
    thread_ids = [k.get("thread_id") for k in data.get("kpis", []) if k.get("thread_id")]
    msgs_by_thread = msg_svc.get_messages_for_threads("analysis", thread_ids)
    for k in data.get("kpis", []):
        k["messages"] = msgs_by_thread.get(str(k.get("thread_id")), [])
    data["kpi_cache"] = {
        "refreshed_at": refreshed_at.strftime("%Y-%m-%d %H:%M:%S") if refreshed_at else "",
    }
    _DASHBOARD_CACHE["payload"] = data
    _DASHBOARD_CACHE["ts"] = time.time()
    return data


def _compute_fpa_outputs(scenario, months, gl_month, budget_month, segments, billings_month, _uri) -> dict:
    """Compute the four FP&A outputs: budget attainment, concentration risk, projection, trend."""
    from backend.storage.duckdb_client import query_rows

    gl_total = sum(gl_month.get(m, 0.0) for m in months)
    budget_total = sum(budget_month.get(m, 0.0) for m in months)
    attainment_pct = (gl_total / budget_total * 100) if budget_total else None

    # Budget attainment by segment (latest month)
    latest_month = months[-1] if months else None
    seg_attainment = []
    if latest_month:
        seg_rows = query_rows(f"""
            WITH inv AS (
                SELECT invoice_id, customer_id,
                       strftime(invoice_date, '%Y-%m') AS ym
                FROM read_parquet('{_uri(scenario, "invoices")}')
            ),
            bil AS (
                SELECT * FROM read_parquet('{_uri(scenario, "invoice_lines")}')
                WHERE invoice_id IS NOT NULL
            ),
            gl AS (
                SELECT period, SUM(recognized_revenue_amt) AS amt
                FROM read_parquet('{_uri(scenario, "gl_revenue")}')
                GROUP BY period
            )
            SELECT COALESCE(c.segment, 'Unknown') AS segment,
                   SUM(bil.line_subtotal) AS billings
            FROM bil
            JOIN inv i ON bil.invoice_id = i.invoice_id
            JOIN read_parquet('{_uri(scenario, "customers")}') c
                 ON i.customer_id = c.customer_id
            WHERE i.ym = '{latest_month}'
            GROUP BY 1
        """)
        seg_attainment = [
            {"segment": r["segment"], "billings": float(r["billings"])}
            for r in seg_rows
        ]
        seg_attainment.sort(key=lambda s: -s["billings"])

    # Revenue concentration: top 5 customers by billings
    conc_rows = query_rows(f"""
        WITH inv AS (
            SELECT invoice_id, customer_id
            FROM read_parquet('{_uri(scenario, "invoices")}')
        ),
        bil AS (
            SELECT * FROM read_parquet('{_uri(scenario, "invoice_lines")}')
            WHERE invoice_id IS NOT NULL
        )
        SELECT i.customer_id, SUM(bil.line_subtotal) AS total
        FROM bil
        JOIN inv i ON bil.invoice_id = i.invoice_id
        GROUP BY 1
        ORDER BY 2 DESC
        LIMIT 5
    """)
    total_billings = sum(float(r["total"]) for r in conc_rows) if conc_rows else 0
    all_billings = sum(billings_month.get(m, 0.0) for m in months)
    top5_share = (total_billings / all_billings * 100) if all_billings else None

    # Projection: linear trend of last 3 months GL revenue
    gl_values = [gl_month.get(m, 0.0) for m in months]
    last3 = gl_values[-3:] if len(gl_values) >= 3 else gl_values
    if len(last3) >= 2:
        growth_rates = [
            (last3[i] - last3[i-1]) / last3[i-1]
            for i in range(1, len(last3))
            if last3[i-1] != 0
        ]
        avg_growth = sum(growth_rates) / len(growth_rates) if growth_rates else 0
    else:
        avg_growth = 0
    projected = []
    if gl_values and avg_growth is not None:
        last_val = gl_values[-1]
        for i in range(1, 4):
            projected.append(last_val * (1 + avg_growth) ** i)

    # Trend analysis: month-over-month growth rates
    trend_labels = months[1:] if len(months) > 1 else []
    growth_rates_full = []
    for i in range(1, len(months)):
        prev = gl_month.get(months[i-1], 0.0)
        curr = gl_month.get(months[i], 0.0)
        if prev > 0:
            growth_rates_full.append(round((curr - prev) / prev * 100, 1))
        else:
            growth_rates_full.append(None)

    # Inflection: last 3 growth rates
    recent_growth = [g for g in growth_rates_full if g is not None][-3:]
    inflection = None
    if len(recent_growth) >= 2:
        if all(recent_growth[i] < recent_growth[i-1] for i in range(1, len(recent_growth))):
            inflection = "decelerating"
        elif all(recent_growth[i] > recent_growth[i-1] for i in range(1, len(recent_growth))):
            inflection = "accelerating"

    return {
        "budget_attainment": {
            "pct": round(attainment_pct, 1) if attainment_pct is not None else None,
            "by_segment": seg_attainment,
        },
        "concentration": {
            "top5_share": round(top5_share, 1) if top5_share is not None else None,
            "customers": [
                {"customer_id": r["customer_id"], "total": float(r["total"])}
                for r in conc_rows
            ],
        },
        "projection": {
            "avg_growth_pct": round(avg_growth * 100, 1) if avg_growth is not None else None,
            "next_3m": [round(p / 1e6, 3) for p in projected],
        },
        "trend": {
            "labels": trend_labels,
            "growth_rates": growth_rates_full,
            "inflection": inflection,
        },
    }


def _process_kpis_only(run_rate, prev_rate, exc_row, pub_count) -> list[dict]:
    """Open Exceptions / DQ Pass Rate / Published Runs (no parquet needed)."""
    dq_delta = None
    trend = "up"
    if run_rate and prev_rate and prev_rate["pass_rate"] is not None:
        dq = float(run_rate["pass_rate"] or 0)
        dq_prev = float(prev_rate["pass_rate"] or 0)
        dq_delta = f"{dq - dq_prev:+.1f}pp vs prev run"
        trend = "up" if dq >= dq_prev else "down"
    return [
        {
            "id": "exceptions_open",
            "title": "Open Exceptions",
            "value": str(exc_row["open_n"]) if exc_row else "0",
            "delta": "open",
            "trend": "up",
            "thread_id": "kpi-exceptions",
        },
        {
            "id": "dq_pass_rate",
            "title": "DQ Pass Rate",
            "value": (
                _fmt_pct(run_rate["pass_rate"]) if run_rate
                and run_rate["pass_rate"] is not None
                else "n/a"
            ),
            "delta": dq_delta or "latest completed run",
            "trend": trend,
            "thread_id": "kpi-dq-pass-rate",
        },
        {
            "id": "published_runs",
            "title": "Published Runs",
            "value": str(pub_count["n"]) if pub_count else "0",
            "delta": "go-live",
            "trend": "up",
            "thread_id": "kpi-published-runs",
        },
    ]
