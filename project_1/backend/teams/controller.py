"""Controller agent skeleton.

The Controller monitors published data reliability on a schedule and posts
triage notes when alerts fire. This is the skeleton — full verification
logic comes in Phase 3.
"""

import logging

from backend.services import llm_client
from backend.services import messages as msg_svc
from backend.skills import load_skill
from backend.teams.base import BaseAgent

logger = logging.getLogger(__name__)


class ControllerAgent(BaseAgent):
    """Controller agent — verification findings and alert triage."""

    def __init__(self):
        super().__init__("controller")

    def post_verification_finding(
        self,
        anchor_type: str,
        anchor_id: str,
        finding: str,
        severity: str = "medium",
        trace_id: str | None = None,
    ) -> dict:
        """Post a verification finding to the given anchor thread.

        Args:
            anchor_type: 'run', 'exception', or 'analysis'.
            anchor_id: The anchor row identifier.
            finding: Human-readable description of what was found.
            severity: One of 'critical', 'high', 'medium', 'low'.
            trace_id: Distributed trace identifier.

        Returns:
            The posted message dict.
        """
        msg = msg_svc.post_message(
            anchor_type,
            str(anchor_id),
            self.persona,
            finding,
            trace_id=trace_id,
            evidence={"severity": severity, "finding": True},
        )

        self.log_action(
            "verification_finding",
            anchor_type,
            str(anchor_id),
            trace_id,
            {"severity": severity, "finding": finding},
        )

        return msg

    def post_alert_triage(
        self,
        alert_type: str,
        anchor_type: str,
        anchor_id: str,
        severity: str,
        detail: str,
        trace_id: str | None = None,
    ) -> dict:
        """Post an alert triage note using the controller_triage_note skill.

        Args:
            alert_type: Type of alert (e.g. 'STALE_PUBLISHED').
            anchor_type: 'run', 'exception', or 'analysis'.
            anchor_id: The anchor row identifier.
            severity: One of 'critical', 'high', 'medium', 'low'.
            detail: Human-readable description of the alert.
            trace_id: Distributed trace identifier.

        Returns:
            The posted message dict.
        """
        try:
            skill_text = load_skill("controller_triage_note")
        except (ValueError, FileNotFoundError):
            skill_text = ""

        user_prompt = (
            f"Alert type: {alert_type}\n"
            f"Severity: {severity}\n"
            f"Detail: {detail}"
        )

        if skill_text:
            content = llm_client.call_llm(skill_text, user_prompt)
        else:
            content = llm_client._template_fallback(user_prompt)

        msg = msg_svc.post_message(
            anchor_type,
            str(anchor_id),
            self.persona,
            content,
            trace_id=trace_id,
            evidence={"alert_type": alert_type, "severity": severity, "triage": True},
        )

        self.log_action(
            "alert_triage",
            anchor_type,
            str(anchor_id),
            trace_id,
            {"alert_type": alert_type, "severity": severity},
        )

        return msg
