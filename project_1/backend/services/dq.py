"""Data Quality agent (deterministic summary; template fallback prose).

The DQ agent executes the validation rules (in ``validations`` / the
orchestrator) and posts a short summary on the run thread. Prose is produced
by a template for now; an LLM call can be layered on later without changing
the numbers.
"""

import json

from backend.db.connection import execute
from backend.services import messages as msg_svc
from backend.services import stub_data


def build_summary(results, recon=None):
    """Render the deterministic validation summary (template fallback)."""
    total = len(results)
    failed = [r for r in results if r["status"] != "pass"]
    lines = [
        f"DQ validation summary: {total} rules executed, {len(failed)} failed.",
    ]
    if failed:
        detail = ", ".join(
            f"{r['rule_id']} ({r['summary_count']})" for r in failed
        )
        lines.append(f"Failed rules: {detail}.")
    else:
        lines.append("All rules passed.")
    if recon is not None:
        lines.append(
            "Reconciliation: "
            f"{recon['rows']} rows, {recon['failed']} above tolerance, "
            f"{recon['exceptions_created']} exception(s) created."
        )
    return "\n".join(lines)


def post_validation_summary(run_id, results, recon=None, trace_id=None):
    content = build_summary(results, recon)
    persona = stub_data.get_persona("dq")
    msg_svc.post_message(
        "run",
        str(run_id),
        persona,
        content,
        trace_id=trace_id,
        evidence={"failed_rules": [r["rule_id"] for r in results if r["status"] != "pass"]},
    )
    execute(
        """
        INSERT INTO agent_actions (agent_id, action, anchor_type, anchor_id, trace_id, payload)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            "dq",
            "validation_summary",
            "run",
            str(run_id),
            trace_id,
            json.dumps(
                {
                    "total": len(results),
                    "failed": [r["rule_id"] for r in results if r["status"] != "pass"],
                    "reconciliation": recon,
                }
            ),
        ),
    )
    return content
