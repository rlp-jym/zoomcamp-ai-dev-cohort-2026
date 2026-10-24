"""Audit ledger formatting helpers."""

from __future__ import annotations

import json
from datetime import datetime


def format_timestamp(value) -> str:
    """Format a DB timestamp as ``Oct 24, 2026, 4:03 PM``."""
    if value is None:
        return "—"
    if isinstance(value, datetime):
        hour = value.strftime("%I:%M %p").lstrip("0")
        return f"{value.strftime('%b')} {value.day}, {value.year}, {hour}"
    return str(value)


def format_payload(payload, limit: int = 140) -> str:
    """Render a JSON payload as a compact, human-readable string."""
    if payload is None or payload == "":
        return "—"
    if isinstance(payload, str):
        text = payload.strip()
        try:
            payload = json.loads(text)
        except (TypeError, ValueError):
            return _truncate(text, limit)
    if not isinstance(payload, dict):
        return _truncate(str(payload), limit)

    parts = []
    for key, value in payload.items():
        if len(parts) >= 4:
            break
        if isinstance(value, (dict, list)):
            value = json.dumps(value, default=str, separators=(",", ":"))
        label_key = str(key)[:-3] if str(key).endswith("_id") else str(key)
        label = label_key.replace("_", " ").title()
        parts.append(f"{label}: {value}")
    return _truncate(" · ".join(parts), limit)


def action_label(action: str) -> str:
    """Turn an agent action slug into a readable verb phrase."""
    if not action:
        return "—"
    return str(action).replace("_", " ").strip().title()


def approval_action(decision: str, target_type: str) -> str:
    verb = "Approved" if str(decision).lower() == "approved" else "Rejected"
    target = "Go-Live" if target_type == "run" else "Remediation"
    return f"{verb} {target}"


def target_label(target_type, target_id) -> str:
    if not target_type or target_id in (None, ""):
        return "—"
    if target_type == "run":
        return f"Run #{target_id}"
    if target_type == "exception":
        return f"Issue #{target_id}"
    return f"{str(target_type).replace('_', ' ').title()} #{target_id}"


def _truncate(value: str, limit: int) -> str:
    text = " ".join(str(value).split())
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)].rstrip() + "…"
