"""Orchestrator service: runs the validate -> reconcile -> exceptions pipeline."""

import json
import time
import uuid
from datetime import datetime

from backend.config import settings
from backend.db.connection import execute, execute_many, fetch_one
from backend.services import dq as dq_svc
from backend.services import messages as msg_svc
from backend.services import reconciliations as recon_svc
from backend.services import runs as runs_svc
from backend.services import stub_data
from backend.services import validations as val_svc
from backend.storage.duckdb_client import open_connection, query_dicts_on
from backend.teams.de import DEAgent
from backend.teams.fa import FAAgent


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


def _period_key(value):
    """Normalize a period value to a 'YYYY-MM' key when possible."""
    if value is None:
        return None
    s = str(value).strip()
    if len(s) >= 7 and s[4] == "-":
        return s[:7]
    return s


def _latest_data_period(conn, scenario_name):
    """Return the latest period present in the GL revenue data."""
    try:
        rows = query_dicts_on(
            conn,
            f"SELECT MAX(period) AS period "
            f"FROM read_parquet('s3://{settings.r2_bucket}/scenarios/{scenario_name}/gl_revenue.parquet') "
            f"WHERE version = 1",
        )
        if rows and rows[0].get("period") is not None:
            return _period_key(rows[0]["period"])
    except Exception:
        pass
    return None


def _create_rule_exceptions(run_id, result, trace_id, latest_period=None):
    """Create one exception per affected period (month) for a failed rule.

    Only the current (latest) period stays 'open'; earlier periods are
    inserted as 'resolved' with details.auto_resolved=true so the
    exceptions list stays a pending work queue while the historical
    record remains available for trend analysis.
    """
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
        p_key = _period_key(period)
        is_current = (p_key is None) or (latest_period is None) or (p_key == latest_period)
        status = "open" if is_current else "resolved"
        details = {"count": count, "sample": rows[:5]}
        if status == "resolved":
            details["auto_resolved"] = True
            details["resolution"] = "closed within period"
        params.append(
            (
                run_id,
                "validation",
                severity,
                str(period) if period else None,
                title,
                status,
                trace_id,
                rule_id,
                json.dumps(details, default=str),
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


def _close_superseded_exceptions(run_id, scenario_name):
    """Close open exceptions raised by runs this run supersedes.

    The exceptions page is a pending work queue for the *current* run: a new
    run re-detects the same issues, so leaving the previous run's exceptions
    open would double-count the backlog. Returns the number closed.
    """
    res = execute(
        """
        UPDATE exceptions
        SET status = 'resolved', updated_at = now()
        WHERE status <> 'resolved'
          AND run_id IS DISTINCT FROM %s
          AND run_id IN (SELECT run_id FROM runs WHERE scenario_name = %s)
        RETURNING exception_id
        """,
        (run_id, scenario_name),
        fetch=True,
    )
    if not res:
        return 0
    _cols, rows = res
    return len(rows) if rows else 0


def run_pipeline(run_id):
    run = runs_svc.get_run(run_id)
    if not run:
        raise RuntimeError(f"run {run_id} not found")
    trace_id = run["trace_id"] or uuid.uuid4().hex
    scenario_name = run["scenario"]
    try:
        from backend.storage.s3_client import resolve_scenario_name

        scenario_name = resolve_scenario_name(scenario_name)
    except Exception:
        try:
            row = fetch_one("SELECT source_scenario FROM scenarios WHERE name = %s", (scenario_name,))
            if row and row.get("source_scenario"):
                scenario_name = row["source_scenario"]
        except Exception:
            pass
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
    open_exceptions = 0

    execute(
        "DELETE FROM exceptions WHERE run_id = %s AND type IN ('validation', 'reconciliation')",
        (run_id,),
    )

    try:
        conn = open_connection()
        try:
            latest_period = _latest_data_period(conn, scenario_name)
            results = val_svc.execute_all_rules(conn, run_id, scenario_name)
            recon = recon_svc.run_reconciliation(conn, run_id, scenario_name, trace_id, latest_period)
        finally:
            conn.close()

        validations_total = len(results)
        validations_failed = sum(1 for r in results if r["status"] != "pass")
        for result in results:
            exceptions_created += _create_rule_exceptions(run_id, result, trace_id, latest_period)
        exceptions_created += recon["exceptions_created"]

        row = fetch_one("SELECT COUNT(*) AS c FROM exceptions WHERE run_id = %s AND status = 'open'", (run_id,))
        open_exceptions = row["c"] if row else 0

        dq_svc.post_validation_summary(run_id, results, recon, trace_id)

        # DE + FA are independent; run them concurrently to keep large runs
        # bounded (each posts one message per open exception, capped).
        from concurrent.futures import ThreadPoolExecutor

        de_agent = DEAgent()
        fa_agent = FAAgent()
        with ThreadPoolExecutor(max_workers=2) as pool:
            de_future = pool.submit(
                de_agent.propose_remediation_for_run, run_id, trace_id
            )
            fa_future = pool.submit(
                fa_agent.quantify_impact_for_run, run_id, trace_id
            )
            de_future.result()
            fa_future.result()

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
        superseded = _close_superseded_exceptions(run_id, scenario_name)
        msg_svc.post_message(
            anchor_type,
            anchor_id,
            _persona("orchestrator"),
            f"Run finished: {validations_total} validation(s) executed, {validations_failed} failed, "
            f"{exceptions_created} exception(s) recorded ({open_exceptions} open, "
            f"{exceptions_created - open_exceptions} auto-closed). "
            f"Reconciliation: {recon['rows']} rows, {recon['failed']} above tolerance."
            + (f" {superseded} exception(s) from superseded runs closed." if superseded else ""),
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
                "open_exceptions": open_exceptions,
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