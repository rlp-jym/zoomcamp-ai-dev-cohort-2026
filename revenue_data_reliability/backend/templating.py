"""Jinja2 template configuration."""

import re

from fastapi.templating import Jinja2Templates

from backend.config import TEMPLATES_DIR
from backend.services import stub_data

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
# Make persona list available in all templates without per-route plumbing.
templates.env.globals["PERSONAS"] = stub_data.PERSONAS


def scenario_label(name):
    """Turn a raw scenario slug into a human-readable dataset label."""
    if not name:
        return ""
    if name == "baseline_run":
        return "Baseline Run"
    match = re.match(r"^(?:generated_)?seed(\d+)_y(\d+)$", name)
    if match:
        return f"Seed {match.group(1)} (Year {match.group(2)})"
    match = re.match(r"^baseline_seed(\d+)_y(\d+)$", name)
    if match:
        return f"Baseline Seed {match.group(1)} (Year {match.group(2)})"
    return name.replace("_", " ").title()


def dataset_label(name):
    """Short dataset label without the years-to-backtrack suffix."""
    label = scenario_label(name)
    match = re.match(r"^(.*?)\s*\(Year \d+\)$", label)
    return match.group(1) if match else label


def human_value(value):
    """Render booleans/nulls consistently for tables and detail summaries."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "nan"}:
        return "—"
    if text.lower() == "true":
        return "Yes"
    if text.lower() == "false":
        return "No"
    return text


def persona_label(persona_id):
    """Map a raw persona id to its display title."""
    if not persona_id:
        return ""
    for persona in stub_data.PERSONAS:
        if persona["id"] == persona_id:
            return persona["title"]
    return str(persona_id).replace("_", " ").title()


templates.env.filters["scenario_label"] = scenario_label
templates.env.filters["persona_label"] = persona_label
templates.env.filters["human_value"] = human_value