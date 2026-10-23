"""Billings vs GL reconciliation at (period, account_id, item_category) grain.

Billings are the period's invoice-line subtotals by item category (from
``invoice_lines`` joined to the item master). GL revenue is allocated per
category from the same billings baseline (see ``data/gl_fx.py``), then split
across accounts. We therefore reconcile at the (period, category) grain and
expand each category's billings across its account rows in proportion to each
row's GL share, so every row in a category carries the category-level variance.
Using version = 1 keeps restatements (a separate control) out of the
reconciliation baseline.
"""
import json

from backend.config import settings
from backend.db.connection import execute, execute_many, fetch_one
from backend.services.demo_window import demo_window
from backend.storage.duckdb_client import query_dicts_on
from backend.storage.scenario_cache import (
    ensure_local_scenario,
    localize_sql,
    scenario_s3_prefix,
)

RECON_SQL = """
WITH bill AS (
    SELECT strftime(inv.invoice_date, '%Y-%m') AS period,
           CASE WHEN it.category IN ('Electronics', 'Industrial', 'Office', 'Safety', 'Misc')
                THEN it.category ELSE 'Misc' END AS item_category,
           SUM(il.line_subtotal) AS billings
    FROM read_parquet('s3://{bucket}/scenarios/{scenario}/invoice_lines.parquet') il
    JOIN read_parquet('s3://{bucket}/scenarios/{scenario}/invoices.parquet') inv
         ON il.invoice_id = inv.invoice_id
    JOIN read_parquet('s3://{bucket}/scenarios/{scenario}/items.parquet') it
         ON il.item_id = it.item_id
    WHERE inv.invoice_date >= DATE '{window_start_date}'
      AND inv.invoice_date < DATE '{window_end_date}'
    GROUP BY 1, 2
), gl AS (
    SELECT period, account_id, item_category,
           recognized_revenue_amt AS gl,
           SUM(recognized_revenue_amt) OVER (PARTITION BY period, item_category) AS gl_cat
    FROM read_parquet('s3://{bucket}/scenarios/{scenario}/gl_revenue.parquet')
    WHERE version = 1
      AND period >= '{window_start_period}'
      AND period <= '{window_end_period}'
)
SELECT gl.period, gl.account_id, gl.item_category,
       bill.billings * gl.gl / gl.gl_cat AS billings,
       gl.gl AS gl,
       (bill.billings * gl.gl / gl.gl_cat - gl.gl) / gl.gl AS variance_pct
FROM gl JOIN bill ON gl.period = bill.period AND gl.item_category = bill.item_category
ORDER BY gl.period, gl.account_id, gl.item_category
"""


def _severity(variance_pct):
    magnitude = abs(variance_pct)
    if magnitude >= 0.02:
        return "critical"
    if magnitude >= 0.01:
        return "high"
    return "medium"


def compute_reconciliation(conn, scenario_name, cache_scenario=None, years_to_backtrack=None):
    """Run the reconciliation scan once and return every grain."""
    from backend.storage.s3_client import resolve_scenario_name

    scenario_name = resolve_scenario_name(scenario_name)
    cache_name = cache_scenario or scenario_name
    ensure_local_scenario(cache_name, scenario_s3_prefix(scenario_name))
    window = demo_window(years_to_backtrack)
    sql = localize_sql(
        RECON_SQL.format(
            bucket=settings.r2_bucket,
            scenario=scenario_name,
            window_start_period=window.start_period,
            window_end_period=window.end_period,
            window_start_date=window.start_date,
            window_end_date=window.end_date,
        ),
        scenario_name,
        cache_name,
    )
    return query_dicts_on(conn, sql)


def persist_reconciliation(run_id, rows, trace_id=None, latest_period=None):
    """Persist reconciliation rows and open material-gap exceptions."""
    tolerance = settings.recon_tolerance_pct
    if latest_period is None:
        try:
            latest_period = max((str(r["period"])[:7] for r in rows), default=None)
        except Exception:
            latest_period = None

    # Idempotent re-run for this run; both deletes share one round trip.
    execute(
        """
        WITH deleted_exceptions AS (
            DELETE FROM exceptions
            WHERE run_id = %s AND type = 'reconciliation'
            RETURNING 1
        ), deleted_reconciliations AS (
            DELETE FROM reconciliations WHERE run_id = %s RETURNING 1
        )
        SELECT 1
        """,
        (run_id, run_id),
    )

    recon_params = []
    by_period = {}
    passed = 0
    failed = 0

    for r in rows:
        billings = float(r["billings"])
        gl = float(r["gl"])
        variance = float(r["variance_pct"])
        status = "pass" if abs(variance) <= tolerance else "fail"
        recon_params.append(
            (run_id, r["period"], r["account_id"], r["item_category"],
             billings, gl, variance, status)
        )
        if status == "pass":
            passed += 1
            continue
        failed += 1

        # Keep every failing grain in reconcilations, but group the exception
        # per period (one exception per affected month, per SPEC).
        period = str(r["period"])
        bucket = by_period.setdefault(
            period,
            {
                "count": 0,
                "billings": 0.0,
                "gl": 0.0,
                "worst": 0.0,
                "severity": "medium",
                "grains": [],
            },
        )
        bucket["count"] += 1
        bucket["billings"] += billings
        bucket["gl"] += gl
        if abs(variance) > abs(bucket["worst"]):
            bucket["worst"] = variance
            bucket["severity"] = _severity(variance)
        if len(bucket["grains"]) < 10:
            bucket["grains"].append(
                {
                    "account_id": r["account_id"],
                    "item_category": r["item_category"],
                    "billings": billings,
                    "gl": gl,
                    "variance_pct": variance,
                }
            )

    # The exception row must share the validation rule's title and severity so
    # /runs/{id} and /exceptions agree exactly. Dynamic reconciliation math is
    # kept in details["summary"] for the exception detail page.
    from backend.services.validations import EXCEPTION_TITLES

    rule = fetch_one(
        "SELECT severity, description FROM rules WHERE rule_id = %s",
        ("VAL_RECON_BILLINGS_GL",),
    )
    rule_severity = rule["severity"] if rule else "high"
    base_title = EXCEPTION_TITLES.get(
        "VAL_RECON_BILLINGS_GL",
        rule["description"] if rule else "Billings vs General Ledger variance",
    )

    exc_params = []
    for period in sorted(by_period):
        bucket = by_period[period]
        title = base_title
        p_key = str(period)[:7] if period else None
        latest_key = str(latest_period)[:7] if latest_period else None
        is_current = (
            p_key is None
            or latest_period is None
            or p_key == latest_key
        )
        status = "open" if is_current else "resolved"
        details = {
            "period": period,
            "grain_count": bucket["count"],
            "aggregate_billings": bucket["billings"],
            "aggregate_gl": bucket["gl"],
            "worst_variance_pct": bucket["worst"],
            "tolerance": tolerance,
            "grains": bucket["grains"],
            "summary": (
                f"Worst variance {bucket['worst'] * 100:+.2f}% across "
                f"{bucket['count']} grain(s) in {period}"
            ),
        }
        if status == "resolved":
            details["auto_resolved"] = True
            details["resolution"] = "closed within period"
        exc_params.append(
            (
                run_id,
                "reconciliation",
                rule_severity,
                period,
                title,
                status,
                trace_id,
                "VAL_RECON_BILLINGS_GL",
                json.dumps(details, default=str),
            )
        )

    execute_many(
        """
        INSERT INTO reconciliations
            (run_id, period, account_id, item_category, billings, gl, variance_pct, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        recon_params,
    )
    execute_many(
        """
        INSERT INTO exceptions (run_id, type, severity, period, title, status, trace_id, rule_id, details)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        exc_params,
    )

    return {
        "rows": len(rows),
        "passed": passed,
        "failed": failed,
        "exceptions_created": len(exc_params),
        "open_exceptions": sum(1 for p in exc_params if p[5] == "open"),
    }


def run_reconciliation(conn, run_id, scenario_name, trace_id=None, latest_period=None,
                       cache_scenario=None, rows=None, years_to_backtrack=None):
    """Compute and persist reconciliation in one call (backwards compatible)."""
    if rows is None:
        rows = compute_reconciliation(
            conn, scenario_name, cache_scenario, years_to_backtrack
        )
    return persist_reconciliation(run_id, rows, trace_id, latest_period)


def list_reconciliations(run_id):
    from backend.db.connection import fetch_all

    return fetch_all(
        "SELECT * FROM reconciliations WHERE run_id = %s ORDER BY period, account_id, item_category",
        (run_id,),
    )
