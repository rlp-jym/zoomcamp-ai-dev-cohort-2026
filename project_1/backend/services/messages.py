"""In-memory message store for Batch 1 (no database)."""

from backend.services import stub_data

STORE = {}


def _seed():
    for key, msgs in stub_data.THREADS.items():
        STORE[key] = [dict(m) for m in msgs]


_seed()


def _key(anchor_type, anchor_id):
    return (anchor_type, str(anchor_id))


def get_messages(anchor_type, anchor_id):
    key = _key(anchor_type, anchor_id)
    if key not in STORE:
        STORE[key] = []
    return STORE[key]


def post_message(anchor_type, anchor_id, persona, content):
    msgs = get_messages(anchor_type, anchor_id)
    new_msg = {
        "persona_id": persona["id"],
        "persona_title": persona["title"],
        "is_agent": persona["type"] == "agent",
        "content": content,
        "created_at": "just now",
        "evidence": None,
    }
    msgs.append(new_msg)
    return new_msg