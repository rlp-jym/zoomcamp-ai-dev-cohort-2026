"""Base agent class with helper for logging agent actions to the DB.

Every agent (Orchestrator, DQ, DE, FA, Controller) inherits from
``BaseAgent`` so that each agent action produces exactly one row in the
``agent_actions`` table, correlated by ``trace_id``.
"""

import json
from typing import Any

from backend.db.connection import execute
from backend.services import stub_data


class BaseAgent:
    """Base class for all agents.

    Attributes:
        agent_id: Short identifier matching ``personas.persona_id``
            (e.g. ``"dq"``, ``"de"``, ``"fa"``).
    """

    def __init__(self, agent_id: str):
        self.agent_id = agent_id

    @property
    def persona(self) -> dict:
        """Return the persona dict for this agent."""
        return stub_data.get_persona(self.agent_id)

    def log_action(
        self,
        action: str,
        anchor_type: str,
        anchor_id: str,
        trace_id: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Write exactly one row to ``agent_actions``.

        This is the single point through which all agent actions are logged.
        Each call inserts one row carrying the agent_id, action name, anchor,
        trace_id, and an optional JSON payload.

        Args:
            action: Short action name (e.g. ``"validation_summary"``,
                ``"remediation_proposal"``, ``"impact_narrative"``).
            anchor_type: ``"run"``, ``"exception"``, or ``"analysis"``.
            anchor_id: The primary key of the anchor row (as string).
            trace_id: Distributed trace identifier for correlation.
            payload: Optional dict serialised to JSONB.
        """
        execute(
            """
            INSERT INTO agent_actions
                (agent_id, action, anchor_type, anchor_id, trace_id, payload)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                self.agent_id,
                action,
                anchor_type,
                str(anchor_id),
                trace_id,
                json.dumps(payload, default=str) if payload is not None else None,
            ),
        )
