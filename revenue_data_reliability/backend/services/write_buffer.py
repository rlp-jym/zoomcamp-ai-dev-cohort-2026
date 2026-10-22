"""Thread-local buffer for batching discussion-stage DB writes.

Agent discussion produces one message and one action per exception.  Writing
those rows one at a time costs a Neon round trip for every insert, which is the
dominant cost in the discussion stage.  The pipeline wraps the discussion in
``buffered_writes()``; ``messages.post_message`` and the shared action logger
append to the buffer, and the context manager flushes everything with a small
number of ``executemany`` calls on exit.
"""

import json
import threading
from contextlib import contextmanager

from backend.db.connection import execute, execute_many, fetch_all

_state = threading.local()


class WriteBuffer:
    """Collect messages and agent actions for one discussion stage."""

    def __init__(self):
        self.messages: list[tuple] = []
        self.actions: list[tuple] = []

    def add_message(self, anchor_type, anchor_id, persona_id, content, trace_id, evidence):
        evidence_json = json.dumps(evidence) if evidence is not None else None
        self.messages.append(
            (anchor_type, str(anchor_id), persona_id, content, trace_id, evidence_json)
        )

    def add_action(self, agent_id, action, anchor_type, anchor_id, trace_id, payload):
        payload_json = json.dumps(payload, default=str) if payload is not None else None
        self.actions.append(
            (agent_id, action, anchor_type, str(anchor_id), trace_id, payload_json)
        )

    def flush(self):
        if self.messages:
            self._flush_messages()
        if self.actions:
            execute_many(
                """
                INSERT INTO agent_actions
                    (agent_id, action, anchor_type, anchor_id, trace_id, payload)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                self.actions,
            )

    def _flush_messages(self):
        # Ensure every thread has a discussion row, then resolve all ids in one
        # query instead of one upsert per message.
        anchors = sorted({(m[0], m[1]) for m in self.messages})
        anchor_types = [a[0] for a in anchors]
        anchor_ids = [a[1] for a in anchors]
        # Upsert and resolve every discussion id in one statement.
        rows = fetch_all(
            """
            WITH input(anchor_type, anchor_id) AS (
                SELECT * FROM unnest(%s::text[], %s::text[])
            ), upserted AS (
                INSERT INTO discussions (anchor_type, anchor_id)
                SELECT anchor_type, anchor_id FROM input
                ON CONFLICT (anchor_type, anchor_id)
                DO UPDATE SET anchor_type = EXCLUDED.anchor_type
                RETURNING discussion_id, anchor_type, anchor_id
            )
            SELECT discussion_id, anchor_type, anchor_id FROM upserted
            """,
            (anchor_types, anchor_ids),
        )
        discussion_ids = {
            (r["anchor_type"], str(r["anchor_id"])): r["discussion_id"] for r in rows
        }
        message_params = []
        for anchor_type, anchor_id, persona_id, content, trace_id, evidence_json in self.messages:
            discussion_id = discussion_ids.get((anchor_type, anchor_id))
            if discussion_id is None:  # pragma: no cover - guard against races
                continue
            message_params.append(
                (discussion_id, persona_id, content, trace_id, evidence_json)
            )
        execute_many(
            """
            INSERT INTO messages (discussion_id, persona_id, content, trace_id, evidence)
            VALUES (%s, %s, %s, %s, %s)
            """,
            message_params,
        )


def current_buffer():
    """Return the active buffer for this thread, if any."""
    return getattr(_state, "buffer", None)


@contextmanager
def buffered_writes():
    """Defer message/action writes until the context exits."""
    previous = current_buffer()
    buffer = WriteBuffer()
    _state.buffer = buffer
    try:
        yield buffer
    finally:
        _state.buffer = previous
        buffer.flush()


def record_action(agent_id, action, anchor_type, anchor_id, trace_id, payload=None):
    """Append to the active buffer, or write one row immediately."""
    buffer = current_buffer()
    if buffer is not None:
        buffer.add_action(agent_id, action, anchor_type, anchor_id, trace_id, payload)
        return
    execute(
        """
        INSERT INTO agent_actions
            (agent_id, action, anchor_type, anchor_id, trace_id, payload)
        VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            agent_id,
            action,
            anchor_type,
            str(anchor_id),
            trace_id,
            json.dumps(payload, default=str) if payload is not None else None,
        ),
    )
