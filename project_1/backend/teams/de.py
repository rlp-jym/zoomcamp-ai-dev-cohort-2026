"""Data Engineer (DE) agent.

Proposes remediation for open exceptions by:
1. Loading the de_remediation_explanation skill
2. Building context from exception details
3. Calling the LLM (or template fallback)
4. Posting the proposal to the exception thread
5. Logging exactly one agent_actions row
"""

import json
import logging

from backend.db.connection import fetch_all
from backend.services import exceptions as exc_svc
from backend.services import llm_client
from backend.services import messages as msg_svc
from backend.skills import load_skill
from backend.teams.base import BaseAgent

logger = logging.getLogger(__name__)

PLAYBOOK_STEPS = [
    "Re-run the same pipeline for the affected month",
    "Quarantine N records with reason code",
    "Reload FX rates from source (if applicable)",
    "Open an issue-style note on the exception",
    "Escalate to Manager",
]


class DEAgent(BaseAgent):
    """Data Engineer agent — proposes remediation for open exceptions."""

    def __init__(self):
        super().__init__("de")

    def propose_remediation_for_run(self, run_id: str, trace_id: str) -> int:
        """Generate and post remediation proposals for all open exceptions in a run.

        Returns the number of proposals posted.
        """
        exceptions = self._get_open_exceptions(run_id)
        count = 0
        for exc in exceptions:
            self.propose_remediation(exc, trace_id)
            count += 1
        return count

    def _get_open_exceptions(self, run_id: str) -> list[dict]:
        rows = fetch_all(
            """
            SELECT * FROM exceptions
            WHERE run_id = %s AND status = 'open'
            ORDER BY exception_id ASC
            """,
            (run_id,),
        )
        out = []
        for r in rows:
            out.append({
                "exception_id": r["exception_id"],
                "run_id": r["run_id"],
                "type": r["type"],
                "severity": r["severity"],
                "period": r["period"],
                "title": r["title"],
                "status": r["status"],
                "trace_id": r["trace_id"],
                "rule_id": r.get("rule_id"),
                "details": exc_svc._as_json(r.get("details")),
            })
        return out

    def propose_remediation(self, exc: dict, trace_id: str) -> dict:
        """Generate and post a remediation proposal for a single exception."""
        context = self._build_context(exc)

        try:
            skill_text = load_skill("de_remediation_explanation")
        except (ValueError, FileNotFoundError):
            skill_text = ""

        user_prompt = self._build_user_prompt(context)

        if skill_text:
            content = llm_client.call_llm(skill_text, user_prompt)
        else:
            content = llm_client._template_fallback(user_prompt)

        msg = msg_svc.post_message(
            "exception",
            str(exc["exception_id"]),
            self.persona,
            content,
            trace_id=trace_id,
            evidence={"exception_id": exc["exception_id"], "proposal": True},
        )

        self.log_action(
            "remediation_proposal",
            "exception",
            str(exc["exception_id"]),
            trace_id,
            {"exception_id": exc["exception_id"], "exception_type": exc["type"]},
        )

        return msg

    def _build_context(self, exc: dict) -> dict:
        sampled_failures = exc_svc.get_sampled_failures_for_exception(exc)
        recon_rows = exc_svc.get_reconciliation_rows_for_exception(exc)

        return {
            "exception_id": exc["exception_id"],
            "title": exc["title"],
            "exception_type": exc["type"],
            "severity": exc["severity"],
            "period": exc["period"],
            "rule_id": exc.get("rule_id"),
            "details": exc.get("details") or {},
            "sampled_failures": sampled_failures,
            "reconciliation_rows": recon_rows,
            "playbook_steps": PLAYBOOK_STEPS,
        }

    def _build_user_prompt(self, context: dict) -> str:
        lines = [
            f"Exception: {context['title']}",
            f"Type: {context['exception_type']}",
            f"Severity: {context['severity']}",
        ]
        if context.get("period"):
            lines.append(f"Period: {context['period']}")
        if context.get("rule_id"):
            lines.append(f"Rule: {context['rule_id']}")
        if context.get("sampled_failures"):
            lines.append(
                f"Sampled failures: {json.dumps(context['sampled_failures'][:3], default=str)}"
            )
        if context.get("reconciliation_rows"):
            lines.append(
                f"Reconciliation rows: {json.dumps(context['reconciliation_rows'][:3], default=str)}"
            )
        lines.append(f"Playbook steps: {', '.join(context['playbook_steps'])}")
        return "\n".join(lines)
