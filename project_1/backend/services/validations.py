"""Validation execution service (raw SQL + DuckDB)."""

import json

from backend.config import settings
from backend.db.connection import execute, fetch_all, fetch_one
from backend.storage.duckdb_client import run_query


def get_rule(rule_id):
    r = fetch_one("SELECT * FROM rules WHERE rule_id = %s", (rule_id,))
    return r


def execute_val_fk_item_exists(run_id, scenario_name, trace_id=None):
    rule = get_rule("VAL_FK_ITEM_EXISTS")
    if not rule:
        raise RuntimeError("VAL_FK_ITEM_EXISTS rule not seeded")
    sql = rule["sql"].format(bucket=settings.r2_bucket, scenario=scenario_name)
    cols, rows = run_query(sql)
    count = len(rows)
    sampled = []
    for r in rows[:10]:
        sampled.append({c: _jsonable(v) for c, v in zip(cols, r)})
    status = "pass" if count == 0 else "fail"
    execute(
        """
        INSERT INTO validations (run_id, rule_id, status, summary_count, sampled_failures)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (run_id, rule_id) DO UPDATE SET
            status = EXCLUDED.status,
            summary_count = EXCLUDED.summary_count,
            sampled_failures = EXCLUDED.sampled_failures
        """,
        (run_id, "VAL_FK_ITEM_EXISTS", status, count, json.dumps(sampled, default=str)),
    )
    return {
        "rule_id": "VAL_FK_ITEM_EXISTS",
        "status": status,
        "summary_count": count,
        "sampled_failures": sampled,
        "severity": rule["severity"],
        "description": rule["description"],
    }


def _jsonable(v):
    if isinstance(v, (bytes, bytearray)):
        return v.decode("utf-8", errors="replace")
    return v


def list_validations(run_id):
    rows = fetch_all("SELECT * FROM validations WHERE run_id = %s", (run_id,))
    return rows
