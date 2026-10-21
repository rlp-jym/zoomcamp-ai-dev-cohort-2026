"""Validation rule execution service (DuckDB over Parquet + Postgres results)."""

import json

from backend.config import settings
from backend.db.connection import execute, fetch_all, fetch_one
from backend.storage.duckdb_client import query_dicts_on

# Short, human labels used for exceptions raised from a failed rule.
EXCEPTION_TITLES = {
    "VAL_FK_ITEM_EXISTS": "Orphaned item ids in invoice_lines",
    "VAL_DUPLICATE_INVOICE_LINE": "Duplicate invoice lines",
    "VAL_FK_CUSTOMER_EXISTS": "Missing customer mapping",
    "VAL_FRESHNESS_GL": "Stale General Ledger load",
    "VAL_RECON_BILLINGS_GL": "Billings vs General Ledger variance",
    "VAL_RESTATEMENT_DETECTED": "General Ledger restatement detected",
    "VAL_FX_RATE_EXISTS": "Missing FX rate",
    "VAL_FK_BACKORDER_ORDER_LINE": "Orphaned backorder order line",
    "VAL_FK_RETURN_SHIPMENT": "Phantom return shipment",
    "VAL_AR_INVOICE_1TO1": "AR invoice 1:1 invariant",
    "VAL_ORDER_LINE_UNIQUE": "Order line uniqueness invariant",
}


def get_rule(rule_id):
    return fetch_one("SELECT * FROM rules WHERE rule_id = %s", (rule_id,))


def list_rules():
    return fetch_all("SELECT * FROM rules ORDER BY rule_id")


def _jsonable(v):
    if isinstance(v, (bytes, bytearray)):
        return v.decode("utf-8", errors="replace")
    return v


def _render_sql(rule_sql, scenario_name):
    return rule_sql.format(
        bucket=settings.r2_bucket,
        scenario=scenario_name,
        tolerance=settings.recon_tolerance_pct,
    )


def run_rule(conn, rule, scenario_name):
    """Execute a single rule's SQL and return the raw result rows."""
    sql = _render_sql(rule["sql"], scenario_name)
    rows = query_dicts_on(conn, sql)
    count = len(rows)
    sampled = [{c: _jsonable(v) for c, v in row.items()} for row in rows[:10]]
    return {
        "rule_id": rule["rule_id"],
        "status": "pass" if count == 0 else "fail",
        "summary_count": count,
        "severity": rule["severity"],
        "description": rule["description"],
        "expected_detection_rule": rule.get("expected_detection_rule"),
        "sampled_failures": sampled,
        "rows": rows,
    }


def store_validation(run_id, result):
    execute(
        """
        INSERT INTO validations (run_id, rule_id, status, summary_count, sampled_failures)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (run_id, rule_id) DO UPDATE SET
            status = EXCLUDED.status,
            summary_count = EXCLUDED.summary_count,
            sampled_failures = EXCLUDED.sampled_failures
        """,
        (
            run_id,
            result["rule_id"],
            result["status"],
            result["summary_count"],
            json.dumps(result["sampled_failures"], default=str),
        ),
    )


def execute_all_rules(conn, run_id, scenario_name):
    """Run every seeded rule, persist the results, and return them.

    Rules are executed on the shared DuckDB connection so the Parquet files
    are fetched once per pipeline run rather than once per rule.
    """
    results = []
    for rule in list_rules():
        result = run_rule(conn, rule, scenario_name)
        store_validation(run_id, result)
        results.append(result)
    return results


def execute_val_fk_item_exists(run_id, scenario_name, trace_id=None):
    """Backwards-compatible single-rule entry point (used by earlier batch)."""
    rule = get_rule("VAL_FK_ITEM_EXISTS")
    if not rule:
        raise RuntimeError("VAL_FK_ITEM_EXISTS rule not seeded")
    conn = _open()
    try:
        result = run_rule(conn, rule, scenario_name)
    finally:
        conn.close()
    store_validation(run_id, result)
    return result


def _open():
    from backend.storage.duckdb_client import open_connection

    return open_connection()


def list_validations(run_id):
    rows = fetch_all(
        """
        SELECT v.rule_id, v.status, v.summary_count, v.sampled_failures,
               v.created_at, r.severity, r.description
        FROM validations v
        JOIN rules r ON r.rule_id = v.rule_id
        WHERE v.run_id = %s
        ORDER BY v.rule_id
        """,
        (run_id,),
    )
    out = []
    for r in rows:
        out.append(
            {
                "rule_id": r["rule_id"],
                "status": r["status"],
                "summary_count": r["summary_count"],
                "severity": r["severity"],
                "description": r["description"],
            }
        )
    return out


def get_validation(run_id, rule_id):
    r = fetch_one(
        "SELECT * FROM validations WHERE run_id = %s AND rule_id = %s",
        (run_id, rule_id),
    )
    return r
