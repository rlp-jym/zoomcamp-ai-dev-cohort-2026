"""Dashboard service (SPEC §19, §3): real KPIs and chart data.

Every number comes from the published dataset — the published run's
invoice_lines read through ``get_published_data_query`` (quarantine overlay
applied) — plus cheap Postgres counters for process/reliability KPIs.

The big `invoice_lines` scan is materialized once per page load; budget and
gl_revenue are small monthly tables scanned directly.
"""

import logging

from backend.config import settings
from backend.db.connection import fetch_one
from backend.services import alerts as alerts_svc
from backend.services import messages as msg_svc
from backend.services import publications as pub_svc

logger = logging.getLogger(__name__)

SCENARIO = "baseline_run"


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
        SELECT 'billings_mtd', '', '',
               COALESCE(SUM(bil.line_subtotal), 0)
            FROM bil
            JOIN inv i ON bil.invoice_id = i.invoice_id
            WHERE i.ym = (SELECT MAX(ym) FROM inv)
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
    billings_mtd = next(
        (float(r["amt"]) for r in rows_a if r["kind"] == "billings_mtd"), 0.0
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

    mtd_key = months[-1] if months else None
    gl_mtd = gl_month.get(mtd_key, 0.0) if mtd_key else 0.0
    prev_mtd_key = months[-2] if len(months) > 1 else None
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

    variance_rows = query_rows(
        f"""
        SELECT item_category, AVG(variance_pct) AS avg_var, COUNT(*) AS n
        FROM reconciliations
        WHERE run_id = {int(q["run_id"])}
        GROUP BY item_category
        ORDER BY ABS(AVG(variance_pct)) DESC
        LIMIT 5
        """
    )
    exc_trend = fetch_one(
        """
        SELECT array_agg(c) AS series FROM (
            SELECT COUNT(*) AS c
            FROM exceptions
            WHERE status <> 'resolved'
            GROUP BY date_trunc('month', created_at)
            ORDER BY date_trunc('month', created_at)
        )
        """
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
            "values": [round(float(r["avg_var"] or 0), 2) for r in variance_rows],
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
            "open_exceptions": (
                (exc_trend["series"] or []) if exc_trend else []
            ),
        },
        "billings_mtd": _fmt_m(billings_mtd),
    }
    return data


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
