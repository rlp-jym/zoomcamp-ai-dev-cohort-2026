"""Billings vs GL reconciliation at (period, account_id, item_category) grain."""

import json

from backend.config import settings
from backend.db.connection import execute, execute_many
from backend.storage.duckdb_client import query_dicts_on

# Billings are the period's invoice-line subtotals (from invoice_lines).
# GL revenue is allocated across (account_id, item_category) grains with a
# random weight per period, so there is no natural item/customer dimension to
# join billings onto. We therefore allocate the period billings to each grain
# in proportion to that grain's GL share, then variance the allocation against
# the recognized GL amount. Using version = 1 keeps restatements (a separate
# control) out of the reconciliation baseline.
RECON_SQL = """
WITH bill AS (
    SELECT strftime(inv.invoice_date, '%Y-%m') AS period,
           SUM(il.line_subtotal) AS billings
    FROM read_parquet('s3://{bucket}/scenarios/{scenario}/invoice_lines.parquet') il
    JOIN read_parquet('s3://{bucket}/scenarios/{scenario}/invoices.parquet') inv
         ON il.invoice_id = inv.invoice_id
    GROUP BY 1
), gl AS (
    SELECT period, account_id, item_category,
           recognized_revenue_amt AS gl,
           SUM(recognized_revenue_amt) OVER (PARTITION BY period) AS gl_period
    FROM read_parquet('s3://{bucket}/scenarios/{scenario}/gl_revenue.parquet')
    WHERE version = 1
)
SELECT gl.period, gl.account_id, gl.item_category,
       bill.billings * gl.gl / gl.gl_period AS billings,
       gl.gl AS gl,
       (bill.billings * gl.gl / gl.gl_period - gl.gl) / gl.gl AS variance_pct
FROM gl JOIN bill USING (period)
ORDER BY gl.period, gl.account_id, gl.item_category
"""


def _severity(variance_pct):
    magnitude = abs(variance_pct)
    if magnitude >= 0.02:
        return "critical"
    if magnitude >= 0.01:
        return "high"
    return "medium"


def run_reconciliation(conn, run_id, scenario_name, trace_id=None):
    """Compute reconciliation rows, persist them, and open material-gap exceptions."""
    sql = RECON_SQL.format(bucket=settings.r2_bucket, scenario=scenario_name)
    rows = query_dicts_on(conn, sql)
    tolerance = settings.recon_tolerance_pct

    # Idempotent re-run for this run.
    execute("DELETE FROM exceptions WHERE run_id = %s AND type = 'reconciliation'", (run_id,))
    execute("DELETE FROM reconciliations WHERE run_id = %s", (run_id,))

    recon_params = []
    exc_params = []
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
        account_id = r["account_id"]
        item_category = r["item_category"]
        title = (
            f"Billings vs GL variance {variance * 100:+.2f}% "
            f"(account {account_id}, category {item_category})"
        )
        exc_params.append(
            (
                run_id,
                "reconciliation",
                _severity(variance),
                str(r["period"]),
                title,
                "open",
                trace_id,
                "VAL_RECON_BILLINGS_GL",
                json.dumps(
                    {
                        "account_id": account_id,
                        "item_category": item_category,
                        "billings": billings,
                        "gl": gl,
                        "variance_pct": variance,
                        "tolerance": tolerance,
                    },
                    default=str,
                ),
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
    }


def list_reconciliations(run_id):
    from backend.db.connection import fetch_all

    return fetch_all(
        "SELECT * FROM reconciliations WHERE run_id = %s ORDER BY period, account_id, item_category",
        (run_id,),
    )
