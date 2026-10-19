"""Financial Analyst (FA) agent.

Quantifies the financial impact of open exceptions by:
1. Loading the fa_impact_narrative skill
2. Building context from exception details and reconciliation data
3. Calling the LLM (or template fallback)
4. Posting the impact narrative to the exception thread
5. Logging exactly one agent_actions row
"""

import json
import logging

from backend.config import settings
from backend.db.connection import fetch_all
from backend.services import exceptions as exc_svc
from backend.services import llm_client
from backend.services import messages as msg_svc
from backend.skills import load_skill
from backend.teams.base import BaseAgent

logger = logging.getLogger(__name__)


class FAAgent(BaseAgent):
    """Financial Analyst agent — quantifies impact of open exceptions."""

    def __init__(self):
        super().__init__("fa")

    def quantify_impact_for_run(self, run_id: str, trace_id: str) -> int:
        """Generate and post impact narratives for open exceptions in a run.

        Capped at ``MAX_AGENT_MESSAGES_PER_RUN``; the remainder is reported
        in a single summary message.
        """
        exceptions = self._get_open_exceptions(run_id)
        limit = settings.max_agent_messages_per_run
        capped = exceptions[:limit]
        for exc in capped:
            self.quantify_impact(exc, trace_id)
        count = len(capped)
        skipped = len(exceptions) - count
        if skipped > 0:
            msg_svc.post_message(
                "run",
                str(run_id),
                self.persona,
                f"Impact narratives capped at {limit}; "
                f"{skipped} additional exception(s) omitted.",
                trace_id=trace_id,
                evidence={"capped": True, "skipped": skipped},
            )
            self.log_action(
                "impact_capped",
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

    def quantify_impact(self, exc: dict, trace_id: str) -> dict:
        """Generate and post a financial impact narrative for a single exception."""
        context = self._build_context(exc)

        try:
            skill_text = load_skill("fa_impact_narrative")
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
            evidence={"exception_id": exc["exception_id"], "impact_narrative": True},
        )

        self.log_action(
            "impact_narrative",
            "exception",
            str(exc["exception_id"]),
            trace_id,
            {
                "exception_id": exc["exception_id"],
                "exception_type": exc["type"],
                "affected_amount": context.get("affected_amount"),
            },
        )

        return msg

    def _build_context(self, exc: dict) -> dict:
        details = exc.get("details") or {}

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

        # Try to compute affected amount from reconciliation data
        affected_amount = None
        currency = "USD"

        if recon_rows:
            # Sum absolute variance across recon rows for this exception
            total_variance = sum(
                abs(r.get("variance_pct") or 0) * (r.get("gl") or 0)
                for r in recon_rows
            )
            if total_variance > 0:
                affected_amount = round(total_variance, 2)
        elif sampled_failures:
            # Estimate from sampled failures if available
            count = details.get("count", len(sampled_failures)) if isinstance(details, dict) else len(sampled_failures)
            affected_amount = count * 1000  # rough estimate

        return {
            "exception_id": exc["exception_id"],
            "title": exc["title"],
            "exception_type": exc["type"],
            "severity": exc["severity"],
            "period": exc["period"],
            "affected_amount": affected_amount,
            "currency": currency,
            "anchor_type": "exception",
            "anchor_id": str(exc["exception_id"]),
            "sampled_failures": sampled_failures,
            "reconciliation_rows": recon_rows,
        }

    def _build_user_prompt(self, context: dict) -> str:
        lines = [
            f"Exception: {context['title']}",
            f"Type: {context['exception_type']}",
            f"Severity: {context['severity']}",
        ]
        if context.get("period"):
            lines.append(f"Period: {context['period']}")
        if context.get("affected_amount") is not None:
            lines.append(f"Affected amount: {context['affected_amount']} {context['currency']}")
        else:
            lines.append("Affected amount: not yet quantifiable")
        if context.get("reconciliation_rows"):
            lines.append(
                f"Reconciliation data: {json.dumps(context['reconciliation_rows'][:3], default=str)}"
            )
        if context.get("sampled_failures"):
            lines.append(
                f"Sampled failures: {json.dumps(context['sampled_failures'][:3], default=str)}"
            )
        return "\n".join(lines)
