"""Orchestrator service: runs the validate -> reconcile -> exceptions pipeline."""

import json
import logging
import time
import uuid
from datetime import datetime

import psutil

from backend.config import settings
from backend.db.connection import execute, execute_many, fetch_one
from backend.services import dq as dq_svc
from backend.services import reconciliations as recon_svc
from backend.services import runs as runs_svc
from backend.services import stub_data
from backend.services import validations as val_svc
from backend.services.dataset_scale import resolve_years
from backend.services.demo_window import demo_window
from backend.services.write_buffer import buffered_writes, record_action
from backend.storage.duckdb_client import open_connection, query_dicts_on
from backend.storage.scenario_cache import (
    ensure_local_scenario,
    localize_sql,
    scenario_s3_prefix,
)
from backend.teams.de import DEAgent
from backend.teams.fa import FinancialImpactAgent

logger = logging.getLogger(__name__)


def _persona(pid):
    return stub_data.get_persona(pid)


def _log_action(agent_id, action, anchor_type, anchor_id, trace_id, payload=None):
    record_action(agent_id, action, anchor_type, anchor_id, trace_id, payload)


def _post_run_event(
    run_id, persona, content, trace_id, action, payload=None, clear_exceptions=False
):
    """Create the run discussion and post one message + action atomically.

    Combining the inserts into one statement keeps the start/finish events to
    a single Neon round trip instead of several.  The start event can also
    clear the run's previous validation/reconciliation exceptions in the same
    statement.
    """
    clear_cte = ""
    clear_params = ()
    if clear_exceptions:
        clear_cte = """
        cleared AS (
            DELETE FROM exceptions
            WHERE run_id = %s AND type IN ('validation', 'reconciliation')
            RETURNING 1
        ),
        """
        clear_params = (str(run_id),)
    execute(
        f"""
        WITH {clear_cte}d AS (
            INSERT INTO discussions (anchor_type, anchor_id)
            VALUES ('run', %s)
            ON CONFLICT (anchor_type, anchor_id)
            DO UPDATE SET anchor_type = EXCLUDED.anchor_type
            RETURNING discussion_id
        ), m AS (
            INSERT INTO messages (discussion_id, persona_id, content, trace_id)
            SELECT discussion_id, %s, %s, %s FROM d
        )
        INSERT INTO agent_actions
            (agent_id, action, anchor_type, anchor_id, trace_id, payload)
        VALUES (%s, %s, 'run', %s, %s, %s)
        """,
        clear_params
        + (
            str(run_id),
            persona["id"],
            content,
            trace_id,
            persona["id"],
            action,
            str(run_id),
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


def _scenario_years(scenario_name):
    """Resolve a scenario's requested history length for the demo window."""
    try:
        row = fetch_one(
            "SELECT name, years_to_backtrack FROM scenarios WHERE name = %s",
            (scenario_name,),
        )
    except Exception:
        row = None
    return resolve_years(row or {"name": scenario_name})


def _latest_data_period(conn, scenario_name, cache_scenario=None):
    """Return the latest period present in the GL revenue data."""
    cache_name = cache_scenario or scenario_name
    try:
        ensure_local_scenario(cache_name, scenario_s3_prefix(scenario_name))
        sql = localize_sql(
            f"SELECT MAX(period) AS period "
            f"FROM read_parquet('s3://{settings.r2_bucket}/scenarios/{scenario_name}/gl_revenue.parquet') "
            f"WHERE version = 1",
            scenario_name,
            cache_name,
        )
        rows = query_dicts_on(conn, sql)
        if rows and rows[0].get("period") is not None:
            return _period_key(rows[0]["period"])
    except Exception:
        pass
    return None


def _rule_exception_params(run_id, result, trace_id, latest_period=None):
    """Build one exception per affected period (month) for a failed rule.

    Only the current (latest) period stays 'open'; earlier periods are
    inserted as 'resolved' with details.auto_resolved=true so the
    exceptions list stays a pending work queue while the historical
    record remains available for trend analysis.  Returning parameters lets
    the orchestrator insert every failed rule in one round trip.
    """
    if result["status"] == "pass":
        return [], 0

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
        # Keep the rule-level title identical to the Validation Results view;
        # period and record count live in dedicated columns/details.
        title = base_title
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
    open_count = sum(1 for p in params if p[5] == "open")
    return params, open_count


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
    logger.info(
        "Pipeline memory [run %s] base RSS: %.1f MB",
        run_id,
        psutil.Process().memory_info().rss / 1024 / 1024,
    )
    trace_id = run["trace_id"] or uuid.uuid4().hex
    requested_scenario = run["scenario"]
    years_to_backtrack = _scenario_years(requested_scenario)
    window = demo_window(years_to_backtrack)
    logger.info(
        "Pipeline demo window [run %s]: %s..%s (years_to_backtrack=%s)",
        run_id,
        window.start_period,
        window.end_period,
        years_to_backtrack,
    )
    scenario_name = requested_scenario
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
    _post_run_event(
        run_id,
        _persona("orchestrator"),
        f"Run started for scenario {scenario_name} (trace {trace_id}).",
        trace_id,
        "run_started",
        {"scenario": scenario_name},
        clear_exceptions=True,
    )

    started = time.time()
    started_perf = time.perf_counter()
    validations_total = 0
    validations_failed = 0
    exceptions_created = 0
    open_exceptions = 0

    try:
        runs_svc.update_run(run_id, current_stage="Validation", progress_percent=25)
        # Download once into the scenario cache before any DuckDB query.  The
        # requested name (not the resolved source) selects the deduplicated
        # cache folder for generated clones.
        cache_start = time.perf_counter()
        ensure_local_scenario(requested_scenario, scenario_s3_prefix(scenario_name))
        logger.info(
            "Pipeline timing [run %s] Cache preparation: %.2fs",
            run_id,
            time.perf_counter() - cache_start,
        )
        conn = open_connection()
        try:
            dq_start = time.perf_counter()
            latest_period = _latest_data_period(
                conn, scenario_name, cache_scenario=requested_scenario
            )
            recon_rows = recon_svc.compute_reconciliation(
                conn,
                scenario_name,
                cache_scenario=requested_scenario,
                years_to_backtrack=years_to_backtrack,
            )
            results = val_svc.execute_all_rules(
                conn,
                run_id,
                scenario_name,
                cache_scenario=requested_scenario,
                recon_rows=recon_rows,
                years_to_backtrack=years_to_backtrack,
            )
            logger.info(
                "Pipeline timing [run %s] DQ Validation: %.2fs",
                run_id,
                time.perf_counter() - dq_start,
            )
            runs_svc.update_run(run_id, current_stage="Reconciliation", progress_percent=50)
            recon_start = time.perf_counter()
            recon = recon_svc.persist_reconciliation(
                run_id, recon_rows, trace_id, latest_period
            )
            logger.info(
                "Pipeline timing [run %s] Reconciliation: %.2fs",
                run_id,
                time.perf_counter() - recon_start,
            )
        finally:
            conn.close()
        runs_svc.update_run(run_id, current_stage="Discussion", progress_percent=75)

        discussion_start = time.perf_counter()
        with buffered_writes():
            validations_total = len(results)
            validations_failed = sum(1 for r in results if r["status"] != "pass")
            validation_exc_params = []
            validation_open = 0
            for result in results:
                params, open_count = _rule_exception_params(
                    run_id, result, trace_id, latest_period
                )
                if params:
                    _log_action(
                        "dq",
                        "exceptions_created",
                        "run",
                        str(run_id),
                        trace_id,
                        {"rule_id": result["rule_id"], "periods": len(params)},
                    )
                validation_exc_params.extend(params)
                validation_open += open_count
            if validation_exc_params:
                execute_many(
                    """
                    INSERT INTO exceptions
                        (run_id, type, severity, period, title, status,
                         trace_id, rule_id, details)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    validation_exc_params,
                )
            exceptions_created = (
                len(validation_exc_params) + recon["exceptions_created"]
            )
            open_exceptions = validation_open + recon.get("open_exceptions", 0)

            dq_svc.post_validation_summary(run_id, results, recon, trace_id)

            # Both agents stay inside the single "Discussion" stage.
            de_agent = DEAgent()
            de_start = time.perf_counter()
            de_agent.propose_remediation_for_run(run_id, trace_id)
            logger.info(
                "Pipeline timing [run %s] DE proposals: %.2fs",
                run_id,
                time.perf_counter() - de_start,
            )
            fa_agent = FinancialImpactAgent()
            fa_start = time.perf_counter()
            fa_agent.quantify_impact_for_run(run_id, trace_id)
            logger.info(
                "Pipeline timing [run %s] Financial Impact Agent: %.2fs",
                run_id,
                time.perf_counter() - fa_start,
            )
        logger.info(
            "Pipeline timing [run %s] Agent Discussion: %.2fs",
            run_id,
            time.perf_counter() - discussion_start,
        )

        final_start = time.perf_counter()
        duration = f"{round(time.time() - started, 2)}s"
        runs_svc.update_run(
            run_id,
            status="completed",
            current_stage="Complete",
            progress_percent=100,
            duration_seconds=int(time.time() - started),
            finished_at=datetime.utcnow(),
            duration=duration,
            validations_total=validations_total,
            validations_failed=validations_failed,
            exceptions_created=exceptions_created,
        )
        superseded = _close_superseded_exceptions(run_id, scenario_name)
        _post_run_event(
            run_id,
            _persona("orchestrator"),
            f"Run finished: {validations_total} validation(s) executed, {validations_failed} failed, "
            f"{exceptions_created} exception(s) recorded ({open_exceptions} open, "
            f"{exceptions_created - open_exceptions} auto-closed). "
            f"Reconciliation: {recon['rows']} rows, {recon['failed']} above tolerance."
            + (f" {superseded} exception(s) from superseded runs closed." if superseded else ""),
            trace_id,
            "run_finished",
            {
                "validations_total": validations_total,
                "validations_failed": validations_failed,
                "exceptions_created": exceptions_created,
                "open_exceptions": open_exceptions,
                "reconciliation": recon,
            },
        )
        logger.info(
            "Pipeline timing [run %s] Finalizing: %.2fs",
            run_id,
            time.perf_counter() - final_start,
        )
    except Exception as exc:
        import traceback

        runs_svc.update_run(
            run_id,
            status="failed",
            current_stage="Failed",
            progress_percent=100,
            duration_seconds=int(time.time() - started),
            finished_at=datetime.utcnow(),
            error_message=f"{exc}\n{traceback.format_exc()}",
        )
        _post_run_event(
            run_id,
            _persona("orchestrator"),
            f"Run failed: {exc}",
            trace_id,
            "run_failed",
            {"error": str(exc)},
        )
        raise
    finally:
        logger.info(
            "Pipeline timing [run %s] Total: %.2fs",
            run_id,
            time.perf_counter() - started_perf,
        )