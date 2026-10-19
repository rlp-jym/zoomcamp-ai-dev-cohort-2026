"""Orchestrator service: runs pipeline for a single run."""

import time
import uuid
from datetime import datetime

from backend.db.connection import execute, fetch_one
from backend.services import exceptions as exc_svc
from backend.services import messages as msg_svc
from backend.services import runs as runs_svc
from backend.services import validations as val_svc
from backend.services import stub_data


def _persona(pid):
    return stub_data.get_persona(pid)


def _log_action(agent_id, action, anchor_type, anchor_id, trace_id, payload=None):
    import json

    execute(
        """
        INSERT INTO agent_actions (agent_id, action, anchor_type, anchor_id, trace_id, payload)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (agent_id, action, anchor_type, anchor_id, trace_id, json.dumps(payload) if payload is not None else None),
    )


def run_pipeline(run_id):
    run = runs_svc.get_run(run_id)
    if not run:
        raise RuntimeError(f"run {run_id} not found")
    trace_id = run["trace_id"] or uuid.uuid4().hex
    scenario_name = run["scenario"]
    anchor_type = "run"
    anchor_id = str(run_id)

    # started
    msg_svc.post_message(
        anchor_type,
        anchor_id,
        _persona("orchestrator"),
        f"Run started for scenario {scenario_name} (trace {trace_id}).",
        trace_id=trace_id,
    )
    _log_action("orchestrator", "run_started", anchor_type, anchor_id, trace_id, {"scenario": scenario_name})

    started = time.time()
    validations_total = 0
    validations_failed = 0
    exceptions_created = 0

    try:
        result = val_svc.execute_val_fk_item_exists(run_id, scenario_name, trace_id)
        validations_total = 1
        if result["status"] != "pass":
            validations_failed = 1
            exc_id = exc_svc.create_exception(
                run_id=run_id,
                exc_type="validation",
                severity=result["severity"],
                title="Orphaned item ids in invoice_lines",
                period=None,
                trace_id=trace_id,
                status="open",
            )
            exceptions_created += 1
            # ensure discussion exists for exception
            msg_svc.get_messages("exception", str(exc_id))
            _log_action(
                "orchestrator",
                "exception_created",
                "exception",
                str(exc_id),
                trace_id,
                {"rule_id": result["rule_id"], "count": result["summary_count"]},
            )

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
            f"{exceptions_created} exception(s) created.",
            trace_id=trace_id,
        )
        _log_action("orchestrator", "run_finished", anchor_type, anchor_id, trace_id,
                    {"validations_total": validations_total, "validations_failed": validations_failed,
                     "exceptions_created": exceptions_created})
    except Exception as exc:
        runs_svc.update_run(run_id, status="failed", finished_at=datetime.utcnow())
        msg_svc.post_message(
            anchor_type,
            anchor_id,
            _persona("orchestrator"),
            f"Run failed: {exc}",
            trace_id=trace_id,
        )
        _log_action("orchestrator", "run_failed", anchor_type, anchor_id, trace_id, {"error": str(exc)})
        raise
