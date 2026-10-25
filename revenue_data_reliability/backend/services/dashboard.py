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

# Analysis threads rendered under the dashboard chart cards. Threads are
# deliberately pre-seeded with historical FP&A discussion so the scenario
# date filters can be exercised.
CHART_THREAD_IDS = (
    "chart-revenue-plan",
    "chart-variance-category",
    "chart-growth",
    "chart-segment",
    "chart-category-trend",
    "chart-customer-variance",
    "chart-top-products",
    "chart-top-clients",
)

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
_DASHBOARD_CACHE_TTL = 60.0
_DASHBOARD_REFRESHING: set = set()
_DASHBOARD_BUILDING: set = set()
_DASHBOARD_BUILD_STARTED: dict[str, float] = {}
_DASHBOARD_REFRESH_LOCK = threading.Lock()
_DASHBOARD_BUILD_LOCK = threading.Lock()
_CACHE_BUILD_TIMEOUT_SECONDS = 30


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
    from backend.storage.s3_client import dataset_s3_prefix

    prefix = dataset_s3_prefix(scenario)
    return f"s3://{settings.r2_bucket}/{prefix}{table}.parquet"


def _int_list(values) -> str:
    return ", ".join(str(int(value)) for value in values)


def _customer_filter(values, column: str = "customer_id") -> str:
    """SQL predicate excluding quarantined customers (NULL ids stay valid)."""
    if not values:
        return ""
    return f" AND ({column} IS NULL OR {column} NOT IN ({_int_list(values)}))"


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


def _top_movers(rows: list[dict], divisor: int = 12) -> list[dict]:
    """Build ranked Top-5 + Rest + Total rows from grouped revenue rows."""
    divisor = max(int(divisor), 1)
    normalized = []
    for row in rows:
        total = float(row.get("total_revenue") or 0.0)
        if total <= 0:
            continue
        normalized.append({
            "name": row.get("name") or "Unknown",
            "group": row.get("grp") or "Unknown",
            "total": total,
            "latest": float(row.get("latest_revenue") or 0.0),
        })
    normalized.sort(key=lambda row: -row["total"])

    total_revenue = sum(row["total"] for row in normalized)
    total_latest = sum(row["latest"] for row in normalized)
    group_totals: dict[str, float] = {}
    for row in normalized:
        group_totals[row["group"]] = group_totals.get(row["group"], 0.0) + row["total"]

    def _metrics(row, rank):
        average = row["total"] / divisor
        volatility = (row["latest"] - average) / average * 100 if average else 0.0
        return {
            "rank": rank,
            "group": row["group"],
            "name": row["name"],
            "total_revenue": row["total"],
            "total_pct": row["total"] / total_revenue * 100 if total_revenue else 0.0,
            "group_pct": (
                row["total"] / group_totals[row["group"]] * 100
                if group_totals.get(row["group"]) else 0.0
            ),
            "avg_monthly_revenue": average,
            "volatility_pct": volatility,
        }

    out = [_metrics(row, rank) for rank, row in enumerate(normalized[:5], start=1)]
    top_total = sum(row["total"] for row in normalized[:5])
    top_latest = sum(row["latest"] for row in normalized[:5])
    rest_total = total_revenue - top_total
    rest_latest = total_latest - top_latest
    rest_avg = rest_total / divisor
    out.append({
        "rank": "—",
        "group": "—",
        "name": "Rest",
        "total_revenue": rest_total,
        "total_pct": rest_total / total_revenue * 100 if total_revenue else 0.0,
        "group_pct": None,
        "avg_monthly_revenue": rest_avg,
        "volatility_pct": (
            (rest_latest - rest_avg) / rest_avg * 100 if rest_avg else 0.0
        ),
        "row_class": "row-rest",
    })
    total_avg = total_revenue / divisor
    out.append({
        "rank": "—",
        "group": "—",
        "name": "Total",
        "total_revenue": total_revenue,
        "total_pct": 100.0 if total_revenue else 0.0,
        "group_pct": None,
        "avg_monthly_revenue": total_avg,
        "volatility_pct": (
            (total_latest - total_avg) / total_avg * 100 if total_avg else 0.0
        ),
        "row_class": "row-total",
    })
    return out


def get_dashboard_data(scenario: str = SCENARIO, conn=None) -> dict:
    """All dashboard payload: open-exceptions stat, 3 charts, attainment card, alert badge.

    ``conn`` lets the cache build reuse a single DuckDB session for every
    query, so httpfs/S3 setup happens once per build instead of once per query.
    """
    from backend.storage.duckdb_client import query_dicts_on, query_rows

    def rows(sql: str):
        return query_dicts_on(conn, sql) if conn is not None else query_rows(sql)

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
    quarantine_keys = q.get("quarantine_keys") or {}
    customer_ids = quarantine_keys.get("customer_ids") or []
    customer_filter = _customer_filter(customer_ids)
    customer_filter_plain = (
        f" AND customer_id NOT IN ({_int_list(customer_ids)})"
        if customer_ids else ""
    )

    # ---- one materialized scan of the published invoice lines -------------
    rows_a = rows(f"""
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
            JOIN (
                SELECT * FROM read_parquet('{_uri(scenario, "customers")}')
                WHERE 1 = 1{customer_filter_plain}
            ) c ON i.customer_id = c.customer_id
            GROUP BY 2
        UNION ALL
        SELECT 'segment_month', COALESCE(c.segment, 'Unknown'),
               CAST(i.ym AS VARCHAR), SUM(bil.line_subtotal)
            FROM bil
            JOIN inv i ON bil.invoice_id = i.invoice_id
            JOIN (
                SELECT * FROM read_parquet('{_uri(scenario, "customers")}')
                WHERE 1 = 1{customer_filter_plain}
            ) c ON i.customer_id = c.customer_id
            GROUP BY 2, 3
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
    segments_month: dict[str, dict[str, float]] = {}
    for r in rows_a:
        if r["kind"] == "segment_month" and r["ym"]:
            label = r["label"] or "Unknown"
            segments_month.setdefault(label, {})[r["ym"]] = float(r["amt"])
    billings_total = next(
        (float(r["amt"]) for r in rows_a if r["kind"] == "billings_total"), 0.0
    )

    # ---- small monthly tables: General Ledger revenue and budget ------------
    # A restatement supersedes the row it restates, so only the highest
    # version per (period, account_id, item_category) counts as current GL.
    gl_month = {
        r["period"]: float(r["amt"])
        for r in rows(
            f"""
            SELECT period, SUM(recognized_revenue_amt) AS amt
            FROM (
                SELECT period, account_id, item_category, recognized_revenue_amt,
                       ROW_NUMBER() OVER (
                           PARTITION BY period, account_id, item_category
                           ORDER BY version DESC
                       ) AS rn
                FROM read_parquet('{_uri(scenario, "gl_revenue")}')
                WHERE 1 = 1{customer_filter}
            )
            WHERE rn = 1
            GROUP BY 1
            """
        )
    }
    budget_month = {
        r["ym"]: float(r["amt"])
        for r in rows(f"""
            SELECT strftime(CAST(period AS DATE), '%Y-%m') AS ym,
                   SUM(budget_revenue_amt) AS amt
            FROM read_parquet('{_uri(scenario, "budget")}')
            WHERE 1 = 1{customer_filter}
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
    months_12 = sorted(
        m for m in (set(gl_month) | set(billings_month) | set(budget_month))
        if m in set(full_months)
    )[-12:]
    month_set = set(months)
    month_set_12 = set(months_12)

    top_products: list[dict] = []
    top_clients: list[dict] = []
    if months_12:
        month_sql = ", ".join(f"'{month}'" for month in months_12)
        latest_sql = f"'{months_12[-1]}'"
        product_rows = rows(f"""
            WITH inv AS (
                SELECT invoice_id, customer_id,
                       strftime(invoice_date, '%Y-%m') AS ym
                FROM read_parquet('{_uri(scenario, "invoices")}')
            ),
            bil AS MATERIALIZED ({pubsql})
            SELECT COALESCE(i.category, 'Unknown') AS grp,
                   CASE
                       WHEN i.abc_class IS NULL OR i.abc_class = '' THEN 'Unknown'
                       ELSE 'Class ' || i.abc_class
                   END AS name,
                   SUM(il.line_subtotal) AS total_revenue,
                   SUM(CASE WHEN inv.ym = {latest_sql}
                            THEN il.line_subtotal ELSE 0 END) AS latest_revenue
            FROM bil il
            JOIN inv ON il.invoice_id = inv.invoice_id
            LEFT JOIN read_parquet('{_uri(scenario, "items")}') i
                   ON il.item_id = i.item_id
            WHERE inv.ym IN ({month_sql})
            GROUP BY 1, 2
        """)
        client_rows = rows(f"""
            WITH inv AS (
                SELECT invoice_id, customer_id,
                       strftime(invoice_date, '%Y-%m') AS ym
                FROM read_parquet('{_uri(scenario, "invoices")}')
            ),
            bil AS MATERIALIZED ({pubsql})
            SELECT COALESCE(c.segment, 'Unknown') AS grp,
                   CASE lower(COALESCE(c.activity_tier, ''))
                       WHEN 'high' THEN 'High Activity'
                       WHEN 'med' THEN 'Medium Activity'
                       WHEN 'low' THEN 'Low Activity'
                       ELSE COALESCE(c.activity_tier, 'Unknown')
                   END AS name,
                   SUM(il.line_subtotal) AS total_revenue,
                   SUM(CASE WHEN inv.ym = {latest_sql}
                            THEN il.line_subtotal ELSE 0 END) AS latest_revenue
            FROM bil il
            JOIN inv ON il.invoice_id = inv.invoice_id
            LEFT JOIN read_parquet('{_uri(scenario, "customers")}') c
                   ON inv.customer_id = c.customer_id
            WHERE inv.ym IN ({month_sql})
            GROUP BY 1, 2
        """)
        top_products = _top_movers(product_rows, len(months_12))
        top_clients = _top_movers(client_rows, len(months_12))

    # ---- target vs actual bridge (trailing chart window) -------------------
    # New cache keys only: the existing billings/variance keys stay intact.
    gl_category_rows = rows(f"""
        SELECT period, item_category, SUM(recognized_revenue_amt) AS amt
        FROM (
            SELECT period, account_id, item_category, recognized_revenue_amt,
                   ROW_NUMBER() OVER (
                       PARTITION BY period, account_id, item_category
                       ORDER BY version DESC
                   ) AS rn
            FROM read_parquet('{_uri(scenario, "gl_revenue")}')
            WHERE 1 = 1{customer_filter}
        )
        WHERE rn = 1
        GROUP BY 1, 2
    """)
    budget_category_rows = rows(f"""
        SELECT strftime(CAST(period AS DATE), '%Y-%m') AS period,
               item_category, SUM(budget_revenue_amt) AS amt
        FROM read_parquet('{_uri(scenario, "budget")}')
        WHERE 1 = 1{customer_filter}
        GROUP BY 1, 2
    """)
    actual_by_category: dict[str, float] = {}
    for row in gl_category_rows:
        if row["period"] in month_set:
            category = row["item_category"] or "Unknown"
            actual_by_category[category] = (
                actual_by_category.get(category, 0.0) + float(row["amt"] or 0.0)
            )
    target_by_category: dict[str, float] = {}
    for row in budget_category_rows:
        if row["period"] in month_set:
            category = row["item_category"] or "Unknown"
            target_by_category[category] = (
                target_by_category.get(category, 0.0) + float(row["amt"] or 0.0)
            )
    target_total = sum(target_by_category.values())
    actual_total = sum(actual_by_category.values())

    # Plan is struck from the opening months' mix; actuals keep the current
    # mix. Segments that grew show positive variance and segments that shrank
    # show negative, so the bridge is not single-direction.
    segment_billings = {
        label: sum(amount for month, amount in by_month.items() if month in month_set)
        for label, by_month in segments_month.items()
    }
    opening_months = set(months_12[:3]) if months_12 else set()
    opening_billings = {
        label: sum(
            amount for month, amount in by_month.items() if month in opening_months
        )
        for label, by_month in segments_month.items()
    }
    total_segment_billings = sum(segment_billings.values())
    total_opening_billings = sum(opening_billings.values())
    target_by_segment: dict[str, float] = {}
    actual_by_segment: dict[str, float] = {}
    if total_opening_billings:
        for label, amount in sorted(opening_billings.items()):
            target_by_segment[label] = round(
                target_total * (amount / total_opening_billings), 2
            )
    if total_segment_billings:
        for label, amount in sorted(segment_billings.items()):
            actual_by_segment[label] = round(
                actual_total * (amount / total_segment_billings), 2
            )
    revenue_by_category_monthly: dict[str, dict[str, float]] = {
        month: {} for month in months_12
    }
    for row in gl_category_rows:
        if row["period"] in month_set_12:
            category = row["item_category"] or "Unknown"
            revenue_by_category_monthly[row["period"]][category] = round(
                float(row["amt"] or 0.0), 2
            )

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

    # ---- growth (trailing 12 months) and target attainment ----------------
    gl_values_12 = [gl_month.get(m, 0.0) for m in months_12]
    growth_rates = [
        round((gl_values_12[i] - gl_values_12[i - 1]) / gl_values_12[i - 1] * 100, 1)
        if gl_values_12[i - 1] > 0 else None
        for i in range(1, len(gl_values_12))
    ]
    gl_values = [gl_month.get(m, 0.0) for m in months]

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

    data["target_total"] = round(target_total, 2)
    data["actual_total"] = round(actual_total, 2)
    data["target_by_category"] = {
        key: round(value, 2) for key, value in sorted(target_by_category.items())
    }
    data["actual_by_category"] = {
        key: round(value, 2) for key, value in sorted(actual_by_category.items())
    }
    data["target_by_segment"] = target_by_segment
    data["actual_by_segment"] = actual_by_segment
    data["top_products"] = top_products
    data["top_clients"] = top_clients
    data["revenue_by_category_monthly"] = revenue_by_category_monthly
    data["billings_by_segment_monthly"] = {
        month: {
            label: round(amounts[month], 2)
            for label, amounts in segments_month.items()
            if month in amounts
        }
        for month in months_12
    }
    # gl_revenue has no segment column (its customer_id is null), so allocate
    # each month's GL total using that month's billing mix by segment.
    revenue_by_segment_monthly: dict[str, dict[str, float]] = {}
    for month in months_12:
        monthly_billings = {
            label: amounts.get(month, 0.0)
            for label, amounts in segments_month.items()
            if amounts.get(month, 0.0)
        }
        monthly_total = sum(monthly_billings.values())
        if not monthly_total:
            revenue_by_segment_monthly[month] = {}
            continue
        gl_total_month = gl_month.get(month, 0.0)
        revenue_by_segment_monthly[month] = {
            label: round(gl_total_month * amount / monthly_total, 2)
            for label, amount in sorted(monthly_billings.items())
        }
    data["revenue_by_segment_monthly"] = revenue_by_segment_monthly

    data["charts"] = {
        # One chart carries actuals, billings and target: the General
        # Ledger series used to be drawn twice (once against budget, once
        # against billings). Forward-looking projections now live under
        # Scenarios, not on this actuals page.
        "revenue_plan": {
            "labels": months_12,
            "actual": [
                round(gl_month.get(m, 0.0) / 1e6, 3) for m in months_12
            ],
            "billings": [
                round(billings_month.get(m, 0.0) / 1e6, 3) for m in months_12
            ],
            "budget": [
                round(budget_month[m] / 1e6, 3)
                if budget_month.get(m) is not None else None
                for m in months_12
            ],
        },
        "variance_category": {
            "labels": [r["item_category"] for r in variance_rows],
            "values": [round(float(r["avg_var"] or 0), 4) for r in variance_rows],
        },
        "growth": {
            "labels": months_12[1:],
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


def _minimal_cache(scenario: str, error: str | None = None) -> dict:
    data = {
        "dataset": scenario,
        "dataset_name": scenario,
        "scenario": scenario,
        "published_run": None,
        "available": False,
        "alerts": [],
        "alert_count": 0,
        "kpis": [],
        "charts": {},
        "chart_messages": _chart_messages(),
        "attainment": None,
        "cache_empty": True,
        "target_total": 0.0,
        "actual_total": 0.0,
        "target_by_category": {},
        "actual_by_category": {},
        "target_by_segment": {},
        "actual_by_segment": {},
        "top_products": [],
        "top_clients": [],
        "revenue_by_category_monthly": {},
        "revenue_by_segment_monthly": {},
        "billings_by_segment_monthly": {},
        "data_quality_impact": {
            "raw_billings": 0.0,
            "cleaned_billings": 0.0,
            "delta": 0.0,
            "quarantined_records": 0,
        },
    }
    if error:
        data["cache_error"] = error
    return data


def _store_cache(scenario: str, data: dict) -> None:
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


def refresh_dashboard_cache(scenario: str = SCENARIO) -> str:
    """Recompute the payload (S3 scans) and upsert it into dashboard_cache.

    The query layer aggregates in DuckDB; only small result sets reach Python.
    Concurrent refreshes are rejected so two 430MB scans cannot overlap.
    On failure a minimal empty payload is cached so the dashboard still loads.
    """
    if not _DASHBOARD_BUILD_LOCK.acquire(blocking=False):
        logger.info("Dashboard cache build already running for %s", scenario)
        return "busy"
    logger.info("Dashboard cache build started for %s", scenario)
    try:
        if not pub_svc.get_published_run(scenario):
            logger.info(
                "Dashboard cache: no published run for %s; writing empty payload.",
                scenario,
            )
            _store_cache(scenario, _minimal_cache(scenario))
            return "empty"
        logger.info("Dashboard cache: published run found for %s", scenario)
        try:
            from backend.storage.duckdb_client import open_connection

            conn = open_connection()
            try:
                data = get_dashboard_data(scenario, conn=conn)
                if data.get("available"):
                    logger.info(
                        "Dashboard cache: payload built for %s; computing impact",
                        scenario,
                    )
                    data["data_quality_impact"] = get_raw_vs_cleaned_delta(
                        scenario, conn=conn
                    )
            finally:
                conn.close()
        except Exception as exc:
            logger.exception("Dashboard cache refresh failed for %s", scenario)
            _store_cache(scenario, _minimal_cache(scenario, str(exc)))
            return f"fallback: {exc}"
        if not data.get("available"):
            logger.info("Dashboard: no published dataset — cache left empty.")
            _store_cache(scenario, _minimal_cache(scenario))
            return "empty"
        logger.info("Dashboard cache: writing payload for %s", scenario)
        _store_cache(scenario, data)
        logger.info("Dashboard cache build completed for %s", scenario)
        return "updated"
    except Exception as exc:
        logger.exception("Dashboard cache fallback failed for %s", scenario)
        try:
            _store_cache(scenario, _minimal_cache(scenario, str(exc)))
        except Exception:
            logger.exception("Dashboard minimal cache write failed for %s", scenario)
        return f"error: {exc}"
    finally:
        _DASHBOARD_BUILD_LOCK.release()


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


def start_dashboard_refresh(scenario: str = SCENARIO) -> bool:
    """Kick off an S3-heavy cache rebuild without blocking the request."""
    scenario = str(scenario)
    with _DASHBOARD_REFRESH_LOCK:
        if scenario in _DASHBOARD_BUILDING:
            return False
        _DASHBOARD_BUILDING.add(scenario)
        _DASHBOARD_BUILD_STARTED[scenario] = time.time()

    def _timeout():
        if _DASHBOARD_BUILD_LOCK.acquire(blocking=False):
            # Build already finished; let its normal completion path win.
            _DASHBOARD_BUILD_LOCK.release()
            return
        logger.error(
            "Dashboard cache build exceeded %ss for %s; writing empty payload.",
            _CACHE_BUILD_TIMEOUT_SECONDS,
            scenario,
        )
        try:
            _store_cache(
                scenario,
                _minimal_cache(scenario, "cache build timed out"),
            )
        except Exception:
            logger.exception("Dashboard timeout fallback write failed for %s", scenario)
        with _DASHBOARD_REFRESH_LOCK:
            _DASHBOARD_BUILDING.discard(scenario)
            _DASHBOARD_BUILD_STARTED.pop(scenario, None)

    def _job():
        try:
            refresh_dashboard_cache(scenario)
        except Exception as exc:
            logger.exception("Dashboard cache build failed: %s", exc)
        finally:
            timer.cancel()
            with _DASHBOARD_REFRESH_LOCK:
                _DASHBOARD_BUILDING.discard(scenario)
                _DASHBOARD_BUILD_STARTED.pop(scenario, None)

    timer = threading.Timer(_CACHE_BUILD_TIMEOUT_SECONDS, _timeout)
    timer.daemon = True
    timer.start()
    threading.Thread(
        target=_job,
        name=f"dashboard-refresh-{scenario}",
        daemon=True,
    ).start()
    return True


def dashboard_cache_status(scenario: str = SCENARIO) -> str:
    """Return ``building`` | ``ready`` | ``missing`` for the status poller."""
    scenario = str(scenario)
    timed_out = False
    with _DASHBOARD_REFRESH_LOCK:
        started = _DASHBOARD_BUILD_STARTED.get(scenario)
        if scenario in _DASHBOARD_BUILDING:
            if started and time.time() - started < _CACHE_BUILD_TIMEOUT_SECONDS:
                return "building"
            timed_out = True
            _DASHBOARD_BUILDING.discard(scenario)
            _DASHBOARD_BUILD_STARTED.pop(scenario, None)
    if timed_out:
        logger.error(
            "Dashboard cache status timed out for %s; writing empty payload.",
            scenario,
        )
        try:
            _store_cache(scenario, _minimal_cache(scenario, "cache build timed out"))
        except Exception:
            logger.exception("Dashboard status fallback write failed for %s", scenario)
        return "ready"
    data, _ = get_from_cache(scenario)
    return "ready" if data is not None else "missing"


def get_raw_vs_cleaned_delta(dataset_name: str, conn=None) -> dict:
    """Compare raw invoice-line billings with the published (cleaned) view.

    Read-only: runs one DuckDB aggregate over the dataset's Parquet invoice
    lines and one over the published-data query, which already applies the
    quarantine overlay. Failures degrade to a zero-impact payload so a
    dashboard render never fails because of this metric.
    """
    empty = {
        "raw_billings": 0.0,
        "cleaned_billings": 0.0,
        "delta": 0.0,
        "quarantined_records": 0,
    }
    try:
        query = pub_svc.get_published_data_query(dataset_name)
        if not query:
            return empty
        from backend.storage.duckdb_client import query_dicts_on, query_rows

        def rows(sql: str):
            return query_dicts_on(conn, sql) if conn is not None else query_rows(sql)

        raw_rows = rows(
            "SELECT COALESCE(SUM(line_subtotal), 0) AS amt, COUNT(*) AS n "
            f"FROM read_parquet('{_uri(dataset_name, 'invoice_lines')}')"
        )
        cleaned_rows = rows(
            "SELECT COALESCE(SUM(line_subtotal), 0) AS amt, COUNT(*) AS n "
            f"FROM ({query['sql']}) cleaned"
        )
        raw = raw_rows[0] if raw_rows else {}
        cleaned = cleaned_rows[0] if cleaned_rows else {}
        raw_amt = float(raw.get("amt") or 0.0)
        cleaned_amt = float(cleaned.get("amt") or 0.0)
        return {
            "raw_billings": round(raw_amt, 2),
            "cleaned_billings": round(cleaned_amt, 2),
            "delta": round(raw_amt - cleaned_amt, 2),
            "quarantined_records": max(
                int(raw.get("n") or 0) - int(cleaned.get("n") or 0), 0
            ),
        }
    except Exception:
        logger.warning(
            "Raw vs cleaned delta failed for dataset %s", dataset_name, exc_info=True
        )
        return empty


def _chart_messages() -> dict:
    """Live analysis-thread messages for every dashboard chart card."""
    msgs_by_thread = msg_svc.get_messages_for_threads(
        "analysis", list(CHART_THREAD_IDS)
    )
    return {aid: msgs_by_thread.get(aid, []) for aid in CHART_THREAD_IDS}


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
            "chart_messages": _chart_messages(),
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
    data["chart_messages"] = _chart_messages()
    data["kpi_cache"] = {
        "refreshed_at": refreshed_at.strftime("%Y-%m-%d %I:%M:%S %p") if refreshed_at else "",
    }
    _DASHBOARD_CACHE[scenario] = {"payload": data, "ts": now}
    return data
