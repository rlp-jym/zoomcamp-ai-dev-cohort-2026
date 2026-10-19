"""Orchestrator service: runs the validate -> reconcile -> exceptions pipeline."""

import json
import time
import uuid
from datetime import datetime

from backend.db.connection import execute, execute_many
from backend.services import dq as dq_svc
from backend.services import exceptions as exc_svc
from backend.services import messages as msg_svc
from backend.services import reconciliations as recon_svc
from backend.services import runs as runs_svc
from backend.services import stub_data
from backend.services import validations as val_svc
from backend.storage.duckdb_client import open_connection


def _persona(pid):
    return stub_data.get_persona(pid)


def _log_action(agent_id, action, anchor_type, anchor_id, trace_id, payload=None):
    execute(
        """
        INSERT INTO agent_actions (agent_id, action, anchor_type, anchor_id, trace_id, payload)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            agent_id,
            action,
            anchor_type,
            anchor_id,
            trace_id,
            json.dumps(payload, default=str) if payload is not None else None,
        ),
    )


def _create_rule_exceptions(run_id, result, trace_id):
    """Create one exception per affected period (month) for a failed rule."""
    if result["status"] == "pass":
        return 0

    rule_id = result["rule_id"]
    base_title = val_svc.EXCEPTION_TITLES.get(rule_id, result["description"])
    severity = result["severity"]

    grouped = {}
    for row in result["rows"]:
        period = row.get("period")
        grouped.setdefault(period, []).append(row)

    params = []
    for period, rows in grouped.items():
        count = len(rows)
        if period:
            title = f"{base_title} ({count} record(s) in {period})"
        else:
            title = f"{base_title} ({count} record(s))"
        params.append(
            (
                run_id,
                "validation",
                severity,
                str(period) if period else None,
                title,
                "open",
                trace_id,
                rule_id,
                json.dumps({"count": count, "sample": rows[:5]}, default=str),
            )
        )

    execute_many(
        """
        INSERT INTO exceptions (run_id, type, severity, period, title, status, trace_id, rule_id, details)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        params,
    )
    _log_action(
        "dq",
        "exceptions_created",
        "run",
        str(run_id),
        trace_id,
        {"rule_id": rule_id, "periods": len(params)},
    )
    return len(params)


def run_pipeline(run_id):
    run = runs_svc.get_run(run_id)
    if not run:
        raise RuntimeError(f"run {run_id} not found")
    trace_id = run["trace_id"] or uuid.uuid4().hex
    scenario_name = run["scenario"]
    anchor_type = "run"
    anchor_id = str(run_id)

    msg_svc.post_message(
        anchor_type,
        anchor_id,
        _persona("orchestrator"),
        f"Run started for scenario {scenario_name} (trace {trace_id}).",
        trace_id=trace_id,
    )
    _log_action("orchestrator", "run_started", anchor_type, anchor_id, trace_id,
                {"scenario": scenario_name})

    started = time.time()
    validations_total = 0
    validations_failed = 0
    exceptions_created = 0

    execute(
        "DELETE FROM exceptions WHERE run_id = %s AND type IN ('validation', 'reconciliation')",
        (run_id,),
    )

    try:
        conn = open_connection()
        try:
            results = val_svc.execute_all_rules(conn, run_id, scenario_name)
            recon = recon_svc.run_reconciliation(conn, run_id, scenario_name, trace_id)
        finally:
            conn.close()

        validations_total = len(results)
        validations_failed = sum(1 for r in results if r["status"] != "pass")
        for result in results:
            exceptions_created += _create_rule_exceptions(run_id, result, trace_id)
        exceptions_created += recon["exceptions_created"]

        dq_svc.post_validation_summary(run_id, results, recon, trace_id)

        duration = f"{round(time.time() - started, 2)}s"
        runs_svc.update_run(
            run_id,
            status="completed",
            finished_at=datetime.utcnow(),
            duration=duration,
            validations_total=validations_total,
            validations_failed=validations_failed,
            exceptions_created=exceptions_created,
        )
        msg_svc.post_message(
            anchor_type,
            anchor_id,
            _persona("orchestrator"),
            f"Run finished: {validations_total} validation(s) executed, {validations_failed} failed, "
            f"{exceptions_created} exception(s) created. "
            f"Reconciliation: {recon['rows']} rows, {recon['failed']} above tolerance.",
            trace_id=trace_id,
        )
        _log_action(
            "orchestrator",
            "run_finished",
            anchor_type,
            anchor_id,
            trace_id,
            {
                "validations_total": validations_total,
                "validations_failed": validations_failed,
                "exceptions_created": exceptions_created,
                "reconciliation": recon,
            },
        )
    except Exception as exc:
        runs_svc.update_run(run_id, status="failed", finished_at=datetime.utcnow())
        msg_svc.post_message(
            anchor_type,
            anchor_id,
            _persona("orchestrator"),
            f"Run failed: {exc}",
            trace_id=trace_id,
        )
        _log_action("orchestrator", "run_failed", anchor_type, anchor_id, trace_id,
                    {"error": str(exc)})
        raise
