"""Postgres-backed message store for discussion threads."""

import json
from datetime import datetime

from backend.db.connection import execute, fetch_all, fetch_one
from backend.services import stub_data


def _fmt_dt(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def _ensure_discussion(anchor_type, anchor_id):
    row = fetch_one(
        """
        INSERT INTO discussions (anchor_type, anchor_id)
        VALUES (%s, %s)
        ON CONFLICT (anchor_type, anchor_id)
        DO UPDATE SET anchor_type = EXCLUDED.anchor_type
        RETURNING discussion_id
        """,
        (anchor_type, str(anchor_id)),
    )
    return row["discussion_id"]


def _row_to_msg(r):
    persona = stub_data.get_persona(r["persona_id"]) if r["persona_id"] else None
    title = r.get("title") or (persona["title"] if persona else r["persona_id"])
    is_agent = (persona["type"] == "agent") if persona else False
    # override with DB persona type if available
    # (title column from personas already)
    evidence = r.get("evidence")
    if isinstance(evidence, str):
        try:
            evidence = json.loads(evidence)
        except Exception:
            pass
    return {
        "message_id": r.get("message_id"),
        "persona_id": r["persona_id"],
        "persona_title": title,
        "is_agent": is_agent,
        "content": r["content"],
        "created_at": _fmt_dt(r["created_at"]),
        "evidence": evidence,
        "trace_id": r.get("trace_id"),
    }


def get_messages(anchor_type, anchor_id):
    did = _ensure_discussion(anchor_type, anchor_id)
    rows = fetch_all(
        """
        SELECT m.*, p.title, p.type
        FROM messages m
        LEFT JOIN personas p ON p.persona_id = m.persona_id
        WHERE m.discussion_id = %s
        ORDER BY m.created_at ASC, m.message_id ASC
        """,
        (did,),
    )
    # attach title/type to row dict for conversion
    out = []
    for r in rows:
        rr = dict(r)
        rr["title"] = r.get("title")
        msg = _row_to_msg(rr)
        # fix is_agent based on DB type if present
        if r.get("type"):
            msg["is_agent"] = (r["type"] == "agent")
        out.append(msg)
    return out


def get_messages_for_threads(anchor_type, anchor_ids):
    """Read-only batch fetch of messages for multiple anchors.

    Unlike ``get_messages``, this never creates discussion rows and never
    writes to the database, so it is safe to call from the request path
    (e.g. the dashboard) without adding per-anchor round trips.
    """
    anchor_ids = [str(a) for a in (anchor_ids or [])]
    out = {aid: [] for aid in anchor_ids}
    if not anchor_ids:
        return out

    rows = fetch_all(
        """
        SELECT d.anchor_id, m.*, p.title, p.type
        FROM messages m
        JOIN discussions d ON d.discussion_id = m.discussion_id
        LEFT JOIN personas p ON p.persona_id = m.persona_id
        WHERE d.anchor_type = %s AND d.anchor_id = ANY(%s)
        ORDER BY d.anchor_id, m.created_at ASC, m.message_id ASC
        """,
        (anchor_type, anchor_ids),
    )
    for r in rows:
        rr = dict(r)
        rr["title"] = r.get("title")
        msg = _row_to_msg(rr)
        if r.get("type"):
            msg["is_agent"] = (r["type"] == "agent")
        out.setdefault(str(r["anchor_id"]), []).append(msg)
    return out


def post_message(anchor_type, anchor_id, persona, content, trace_id=None, evidence=None):
    did = _ensure_discussion(anchor_type, anchor_id)
    persona_id = persona["id"] if isinstance(persona, dict) else persona
    execute(
        """
        INSERT INTO messages (discussion_id, persona_id, content, trace_id, evidence)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (did, persona_id, content, trace_id, json.dumps(evidence) if evidence is not None else None),
    )
    # return last message
    row = fetch_one(
        """
        SELECT m.*, p.title, p.type
        FROM messages m
        LEFT JOIN personas p ON p.persona_id = m.persona_id
        WHERE m.discussion_id = %s
        ORDER BY m.message_id DESC
        LIMIT 1
        """,
        (did,),
    )
    rr = dict(row)
    rr["title"] = row.get("title")
    msg = _row_to_msg(rr)
    if row.get("type"):
        msg["is_agent"] = (row["type"] == "agent")
    return msg


def delete_discussion(discussion_id):
    did = int(discussion_id)
    execute("DELETE FROM messages WHERE discussion_id = %s", (did,))
    execute("DELETE FROM discussions WHERE discussion_id = %s", (did,))


def delete_message(message_id):
    execute("DELETE FROM messages WHERE message_id = %s", (int(message_id),))


def delete_discussion_by_anchor(anchor_type, anchor_id):
    row = fetch_one(
        "SELECT discussion_id FROM discussions WHERE anchor_type = %s AND anchor_id = %s",
        (anchor_type, str(anchor_id)),
    )
    if row:
        delete_discussion(row["discussion_id"])
