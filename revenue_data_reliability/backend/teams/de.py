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

from backend.config import settings
from backend.db.connection import execute, fetch_all
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
        """Generate and post remediation proposals for open exceptions in a run.

        Capped at ``MAX_AGENT_MESSAGES_PER_RUN`` to keep large runs bounded;
        the remainder is reported in a single summary message.
        """
        exceptions = self._get_open_exceptions(run_id)
        limit = settings.max_agent_messages_per_run
        capped = exceptions[:limit]
        for exc in capped:
            self.propose_remediation(exc, trace_id)
        count = len(capped)
        skipped = len(exceptions) - count
        if skipped > 0:
            msg_svc.post_message(
                "run",
                str(run_id),
                self.persona,
                f"Remediation proposals capped at {limit}; "
                f"{skipped} additional exception(s) omitted.",
                trace_id=trace_id,
                evidence={"capped": True, "skipped": skipped},
            )
            self.log_action(
                "remediation_capped",
                "run",
                str(run_id),
                trace_id,
                {"limit": limit, "skipped": skipped},
            )
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

    def propose_remediation(self, exc: dict, trace_id: str, rejection_reason: str | None = None) -> dict:
        """Generate and post a remediation proposal for a single exception.

        ``rejection_reason`` is set by the Manager rejection loop; the DE
        agent must address it explicitly in the next proposal.
        """
        context = self._build_context(exc)
        if rejection_reason:
            context["rejection_reason"] = rejection_reason

        try:
            skill_text = load_skill("de_remediation_explanation")
        except (ValueError, FileNotFoundError):
            skill_text = ""

        user_prompt = self._build_user_prompt(context)

        if skill_text:
            content = llm_client.call_llm(skill_text, user_prompt)
        else:
            content = llm_client._template_fallback(user_prompt)

        if llm_client.is_fallback(content):
            content = self._fallback_proposal(context)

        exc_id = exc.get("exception_id", exc.get("id"))
        attempts = int(exc.get("remediation_attempts") or 0) + 1
        execute(
            """
            UPDATE exceptions
            SET status = 'awaiting_approval',
                remediation_attempts = %s,
                updated_at = now()
            WHERE exception_id = %s
            """,
            (attempts, exc_id),
        )

        msg = msg_svc.post_message(
            "exception",
            str(exc_id),
            self.persona,
            content,
            trace_id=trace_id,
            evidence={"exception_id": exc_id, "proposal": True},
        )

        self.log_action(
            "remediation_proposal",
            "exception",
            str(exc_id),
            trace_id,
            {"exception_id": exc_id, "exception_type": exc["type"]},
        )

        return msg

    def execute_remediation(self, exc: dict, trace_id: str) -> None:
        """Log execution of an approved remediation plan.

        This is a bounded-write stub: no actual data is deleted or quarantined.
        Each call logs exactly one agent_actions row with a step description.
        """
        exc_id = exc.get("exception_id", exc.get("id"))
        if exc_id is None:
            raise ValueError("Exception dict is missing an id.")
        details = exc.get("details") or {}
        count = details.get("count", 0) if isinstance(details, dict) else 0

        step_desc = f"Executed remediation: Quarantine {count} records"
        if count == 0:
            step_desc = "Executed remediation: Re-run pipeline for affected month"

        self.log_action(
            "remediation_executed",
            "exception",
            str(exc_id),
            trace_id,
            {"exception_id": exc_id, "step": step_desc},
        )

    def execute_quarantine(self, exc: dict, trace_id: str) -> tuple[int, int]:
        """Quarantine the affected records for an exception (playbook step 2).

        Bounded write: inserts one ``quarantines`` row carrying the affected
        record keys and a reason code derived from the exception, and logs
        exactly one agent_actions row.

        Returns (quarantine_id, record_count).
        """
        from backend.services import quarantines as quarantines_svc

        exc_id = exc.get("exception_id", exc.get("id"))
        if exc_id is None:
            raise ValueError("Exception dict is missing an id.")
        records = exc_svc.get_quarantine_records_for_exception(exc)
        count = len(records)
        rule_id = exc.get("rule_id") or exc.get("type") or "EXCEPTION"
        reason_code = f"QUARANTINE_{str(rule_id).upper()}"

        quarantine_id = quarantines_svc.create_quarantine(
            run_id=exc.get("run_id"),
            exception_id=exc_id,
            reason_code=reason_code,
            record_keys=records,
            created_by=self.agent_id,
        )

        self.log_action(
            "quarantine_executed",
            "exception",
            str(exc_id),
            trace_id,
            {
                "exception_id": exc_id,
                "quarantine_id": quarantine_id,
                "reason_code": reason_code,
                "record_count": count,
            },
        )

        msg_svc.post_message(
            "exception",
            str(exc_id),
            self.persona,
            (
                f"Quarantined {count} record(s) for exception #{exc_id} "
                f"(reason code {reason_code}). These records are excluded "
                f"from the published view for run {exc.get('run_id')}."
            ),
            trace_id=trace_id,
            evidence={
                "quarantine_id": quarantine_id,
                "reason_code": reason_code,
                "record_count": count,
            },
        )

        return quarantine_id, count

    def _fallback_proposal(self, context: dict) -> str:
        details = context.get("details") or {}
        count = details.get("count") or details.get("grain_count") or 0
        period = context.get("period") or details.get("period") or "the affected period"
        rule_id = context.get("rule_id") or "the failed rule"
        if count:
            action = f"Quarantine {count} record(s) for {period}"
        else:
            action = f"Re-run the pipeline for {period}"
        lines = [
            "Remediation Proposal",
            f"Proposed Action: {action}",
            f"Rule: {rule_id}",
        ]
        if context.get("rejection_reason"):
            lines.append(f"Addressed rejection feedback: {context['rejection_reason']}")
        lines.append("Manager: Approve or Reject with a reason to continue.")
        return "\n".join(lines)

    def _build_context(self, exc: dict) -> dict:
        details = exc.get("details") or {}
        exc_id = exc.get("exception_id", exc.get("id"))

        # Prefer data already persisted on the exception (one DB round trip
        # saved per agent message); fall back to a query only when missing.
        if isinstance(details, dict) and "sample" in details:
            sampled_failures = details.get("sample") or []
        elif exc.get("type") == "validation":
            sampled_failures = exc_svc.get_sampled_failures_for_exception(exc)
        else:
            sampled_failures = []

        if isinstance(details, dict) and "grains" in details:
            recon_rows = details.get("grains") or []
        elif exc.get("type") == "reconciliation":
            recon_rows = exc_svc.get_reconciliation_rows_for_exception(exc)
        else:
            recon_rows = []

        return {
            "exception_id": exc_id,
            "title": exc["title"],
            "exception_type": exc["type"],
            "severity": exc["severity"],
            "period": exc["period"],
            "rule_id": exc.get("rule_id"),
            "details": details,
            "sampled_failures": sampled_failures,
            "reconciliation_rows": recon_rows,
            "playbook_steps": PLAYBOOK_STEPS,
        }

    def _build_user_prompt(self, context: dict) -> str:
        lines = [
            f"Data Issue: {context['title']}",
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
        if context.get("rejection_reason"):
            lines.append(f"Manager rejection reason: {context['rejection_reason']}")
            lines.append("Revise the remediation to address this rejection explicitly.")
        lines.append(f"Playbook steps: {', '.join(context['playbook_steps'])}")
        return "\n".join(lines)
