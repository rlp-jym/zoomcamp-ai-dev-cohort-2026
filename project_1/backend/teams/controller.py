"""Controller agent skeleton.

The Controller monitors published data reliability on a schedule and posts
triage notes when alerts fire. Phase 2 implements the ``STALE_PUBLISHED``
verification (logged to ``agent_actions``); the alerts table and the other
five alert types come in Phase 3.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone

from opentelemetry import trace

from backend.config import settings
from backend.db.connection import fetch_one
from backend.services import llm_client
from backend.services import messages as msg_svc
from backend.skills import load_skill
from backend.teams.base import BaseAgent

logger = logging.getLogger(__name__)


class ControllerAgent(BaseAgent):
    """Controller agent — verification findings and alert triage."""

    def __init__(self):
        super().__init__("controller")

    def verify_stale_published(self, trace_id: str | None = None) -> dict | None:
        """Check whether the active publication is older than its SLA.

        Reads the latest ``publications`` row (SPEC §12: the anchor for
        ``STALE_PUBLISHED`` is the published run). If ``published_at`` is
        older than ``CONTROLLER_STALE_HOURS`` (default 24h), logs exactly
        one ``agent_actions`` row — the alert that feeds the Phase 3
        ``alerts`` table. Returns the finding dict, or None if healthy.
        """
        pub = fetch_one(
            """
            SELECT p.publication_id, p.run_id, p.published_at, r.scenario_name
            FROM publications p
            LEFT JOIN runs r ON r.run_id = p.run_id
            ORDER BY p.publication_id DESC
            LIMIT 1
            """
        )
        if not pub:
            logger.info("Controller: no publication yet; nothing to verify.")
            return None

        published_at = pub["published_at"]
        if published_at is None:
            logger.info(
                "Controller: publication #%s has no published_at; skipping.",
                pub["publication_id"],
            )
            return None

        now = datetime.now(timezone.utc)
        threshold = timedelta(hours=settings.controller_stale_hours)
        age = now - published_at
        payload = {
            "publication_id": pub["publication_id"],
            "run_id": pub["run_id"],
            "scenario": pub["scenario_name"],
            "published_at": published_at.isoformat(),
            "age_hours": round(age.total_seconds() / 3600, 2),
            "stale_threshold_hours": settings.controller_stale_hours,
        }

        if age < threshold:
            logger.info(
                "Controller: publication #%s for scenario %s is fresh "
                "(age %.1fh < %.0fh threshold).",
                pub["publication_id"], pub["scenario_name"],
                age.total_seconds() / 3600, threshold.total_seconds() / 3600,
            )
            return None

        finding = (
            f"STALE_PUBLISHED: publication #{pub['publication_id']} for scenario "
            f"{pub['scenario_name']} ran {age.total_seconds() / 3600:.1f}h ago "
            f"(threshold {threshold.total_seconds() / 3600:.0f}h)."
        )
        # Phase 3 wires this into the alerts table; skeleton logs the finding only.
        self.log_action(
            "stale_published_finding",
            "run",
            str(pub["run_id"]),
            trace_id,
            payload,
        )
        logger.warning("Controller: %s", finding)
        return {"finding": finding, **payload}

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


def run_controller_verification() -> dict | None:
    """Scheduler job: run Controller verification inside its own trace.

    Share a ``trace_id`` between the OTEL span tree, agent actions, and
    (in Phase 3) the alerts opened from these findings.
    """
    with trace.get_tracer("scheduler.controller").start_as_current_span(
        "controller.verification_job"
    ) as span:
        ctx = span.get_span_context()
        trace_id = (
            format(ctx.trace_id, "032x")
            if ctx and ctx.trace_id
            else uuid.uuid4().hex
        )
        return ControllerAgent().verify_stale_published(trace_id)
