"""Validation rule execution service (DuckDB over Parquet + Postgres results)."""

import json
import logging
import time

from backend.config import settings
from backend.db.connection import execute, execute_many, fetch_all, fetch_one
from backend.services.demo_window import demo_window
from backend.storage.duckdb_client import query_dicts_on
from backend.storage.scenario_cache import (
    ensure_local_scenario,
    localize_sql,
    scenario_s3_prefix,
)

logger = logging.getLogger(__name__)

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
    "VAL_SEGMENT_DRIFT": "Unrecognised customer segment",
}


def get_rule(rule_id):
    return fetch_one("SELECT * FROM rules WHERE rule_id = %s", (rule_id,))


def list_rules():
    return fetch_all("SELECT * FROM rules ORDER BY rule_id")


def _jsonable(v):
    if isinstance(v, (bytes, bytearray)):
        return v.decode("utf-8", errors="replace")
    return v


def _render_sql(rule_sql, scenario_name, cache_scenario=None, years_to_backtrack=None):
    window = demo_window(years_to_backtrack)
    rendered = rule_sql.format(
        bucket=settings.r2_bucket,
        scenario=scenario_name,
        tolerance=settings.recon_tolerance_pct,
        window_start_period=window.start_period,
        window_end_period=window.end_period,
        window_start_date=window.start_date,
        window_end_date=window.end_date,
    )
    return localize_sql(rendered, scenario_name, cache_scenario)


def _result_from_rows(rule, rows):
    """Build the standard rule result payload from already-fetched rows."""
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


def run_rule(conn, rule, scenario_name, cache_scenario=None, years_to_backtrack=None):
    """Execute a single rule's SQL and return the raw result rows."""
    cache_name = cache_scenario or scenario_name
    ensure_local_scenario(cache_name, scenario_s3_prefix(scenario_name))
    sql = _render_sql(rule["sql"], scenario_name, cache_name, years_to_backtrack)
    query_start = time.perf_counter()
    rows = query_dicts_on(conn, sql)
    logger.info(
        "Validation rule %s: %.2fs (%d row(s))",
        rule["rule_id"],
        time.perf_counter() - query_start,
        len(rows),
    )
    return _result_from_rows(rule, rows)


def result_from_recon_rows(rule, rows):
    """Build VAL_RECON_BILLINGS_GL from a shared reconciliation scan."""
    tolerance = settings.recon_tolerance_pct
    failed = [row for row in rows if abs(float(row["variance_pct"])) > tolerance]
    return _result_from_rows(rule, failed)


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


def store_validations(run_id, results):
    """Persist every rule result for a run in one round trip."""
    execute_many(
        """
        INSERT INTO validations (run_id, rule_id, status, summary_count, sampled_failures)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (run_id, rule_id) DO UPDATE SET
            status = EXCLUDED.status,
            summary_count = EXCLUDED.summary_count,
            sampled_failures = EXCLUDED.sampled_failures
        """,
        [
            (
                run_id,
                result["rule_id"],
                result["status"],
                result["summary_count"],
                json.dumps(result["sampled_failures"], default=str),
            )
            for result in results
        ],
    )


def execute_all_rules(
    conn,
    run_id,
    scenario_name,
    cache_scenario=None,
    recon_rows=None,
    years_to_backtrack=None,
):
    """Run every seeded rule, persist the results, and return them.

    Rules are executed on the shared DuckDB connection so the Parquet files
    are fetched once per pipeline run rather than once per rule.  The original
    scenario name is kept separately for cache-folder selection because
    generated clones resolve to ``baseline_run`` in S3.  ``recon_rows`` lets
    the caller reuse the reconciliation scan for ``VAL_RECON_BILLINGS_GL``.
    ``years_to_backtrack`` narrows the deterministic demo window when the
    scenario promises a shorter history.
    """
    from backend.storage.s3_client import resolve_scenario_name

    scenario_name = resolve_scenario_name(scenario_name)
    cache_name = cache_scenario or scenario_name
    ensure_local_scenario(cache_name, scenario_s3_prefix(scenario_name))
    results = []
    for rule in list_rules():
        if rule["rule_id"] == "VAL_RECON_BILLINGS_GL" and recon_rows is not None:
            results.append(result_from_recon_rows(rule, recon_rows))
            logger.info("Validation rule %s: reused reconciliation scan", rule["rule_id"])
            continue
        results.append(
            run_rule(
                conn,
                rule,
                scenario_name,
                cache_scenario=cache_name,
                years_to_backtrack=years_to_backtrack,
            )
        )
    store_validations(run_id, results)
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
               v.created_at, r.severity, r.description, r.impact
        FROM validations v
        JOIN rules r ON r.rule_id = v.rule_id
        WHERE v.run_id = %s
        ORDER BY CASE r.severity
            WHEN 'critical' THEN 1 WHEN 'high' THEN 2
            WHEN 'medium' THEN 3 WHEN 'low' THEN 4 ELSE 5 END ASC,
            v.created_at DESC, v.rule_id
        """,
        (run_id,),
    )
    out = []
    for r in rows:
        out.append(
            {
                "rule_id": r["rule_id"],
                "title": EXCEPTION_TITLES.get(r["rule_id"], r["description"]),
                "status": r["status"],
                "summary_count": r["summary_count"],
                "severity": r["severity"],
                "impact": r["impact"],
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
