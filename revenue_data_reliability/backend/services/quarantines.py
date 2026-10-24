"""Quarantine service (raw SQL over Postgres).

A quarantine row excludes records from the published view for a run.
``record_keys`` holds the affected record identifiers (e.g. invoice line
ids captured from the exception details or validation samples).
"""

import json
from datetime import datetime

from backend.db.connection import fetch_all, fetch_one


def _fmt_dt(value):
    if value is None:
        return ""
    if isinstance(value, datetime):
        return f"{value:%b} {value.day}, {value:%Y, %I:%M %p}"
    return str(value)


def _reason_label(reason_code):
    if not reason_code:
        return ""
    rule_id = str(reason_code).removeprefix("QUARANTINE_")
    from backend.services.validations import EXCEPTION_TITLES

    if rule_id in EXCEPTION_TITLES:
        return EXCEPTION_TITLES[rule_id]
    row = fetch_one("SELECT description FROM rules WHERE rule_id = %s", (rule_id,))
    if row and row.get("description"):
        return row["description"]
    return str(reason_code).replace("_", " ").title()


def create_quarantine(run_id, exception_id, reason_code, record_keys, created_by):
    """Insert one quarantine row and return its id."""
    row = fetch_one(
        """
        INSERT INTO quarantines (run_id, exception_id, reason_code, record_keys, created_by)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING quarantine_id
        """,
        (
            run_id,
            exception_id,
            reason_code,
            json.dumps(record_keys, default=str) if record_keys is not None else None,
            created_by,
        ),
    )
    return row["quarantine_id"]


def _to_dict(r):
    return {
        "id": r["quarantine_id"],
        "run_id": r["run_id"],
        "exception_id": r["exception_id"],
        "reason_code": r["reason_code"],
        "reason_label": _reason_label(r["reason_code"]),
        "record_keys": json.loads(r["record_keys"]) if isinstance(r["record_keys"], str) else r["record_keys"],
        "created_by": r["created_by"],
        "created_at": _fmt_dt(r["created_at"]),
    }


def get_quarantine(quarantine_id):
    r = fetch_one("SELECT * FROM quarantines WHERE quarantine_id = %s", (quarantine_id,))
    return _to_dict(r) if r else None


def list_quarantines_for_exception(exception_id):
    rows = fetch_all(
        "SELECT * FROM quarantines WHERE exception_id = %s ORDER BY quarantine_id",
        (exception_id,),
    )
    return [_to_dict(r) for r in rows]


def list_quarantines_for_run(run_id):
    rows = fetch_all(
        "SELECT * FROM quarantines WHERE run_id = %s ORDER BY quarantine_id",
        (run_id,),
    )
    return [_to_dict(r) for r in rows]


def _iter_key_entries(record_keys):
    """Yield raw entries from the quarantines.record_keys JSONB shape.

    Accepts a list of records, or a details-style dict that nests records
    under ``sample`` / ``records`` (the exceptions.details shape).
    """
    if record_keys is None:
        return
    if isinstance(record_keys, str):
        try:
            record_keys = json.loads(record_keys)
        except Exception:
            return
    if isinstance(record_keys, dict):
        if "sample" in record_keys or "records" in record_keys:
            yield from _iter_key_entries(record_keys.get("sample", record_keys.get("records")))
            return
        record_keys = [record_keys]
    if not isinstance(record_keys, list):
        return
    for entry in record_keys:
        if isinstance(entry, dict) and ("sample" in entry or "records" in entry):
            yield from _iter_key_entries(entry)
        else:
            yield entry


RECORD_ID_KEYS = (
    "invoice_line_id",
    "line_id",
    "invoice_id",
    "customer_id",
    "item_id",
    "record_key",
)


def _coerce_id(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def extract_record_id(entry, key=None):
    """Extract a record identifier from a quarantine record entry.

    Recognises ``invoice_line_id``, ``line_id``, ``invoice_id``,
    ``customer_id``, ``item_id``, and ``record_key``. ``key`` can restrict
    the lookup to one identifier when building typed filter sets.
    """
    if isinstance(entry, dict):
        candidates = (key,) if key else RECORD_ID_KEYS
        for candidate in candidates:
            value = entry.get(candidate)
            if value is not None:
                return _coerce_id(value)
        return None
    return _coerce_id(entry)


def quarantined_keys(run_id):
    """Typed quarantine identifiers for a run.

    Returns ``invoice_line_ids``, ``invoice_ids``, ``customer_ids``, and
    ``item_ids``. Legacy bare/``record_key`` entries are treated as invoice
    line ids so existing quarantine rows keep working.
    """
    rows = fetch_all(
        "SELECT record_keys FROM quarantines WHERE run_id = %s",
        (run_id,),
    )
    keys = {
        "invoice_line_ids": [],
        "invoice_ids": [],
        "customer_ids": [],
        "item_ids": [],
    }
    for r in rows:
        for entry in _iter_key_entries(r["record_keys"]):
            if not isinstance(entry, dict):
                rid = extract_record_id(entry)
                if rid is not None and rid not in keys["invoice_line_ids"]:
                    keys["invoice_line_ids"].append(rid)
                continue
            for name in ("invoice_line_id", "line_id", "record_key"):
                rid = extract_record_id(entry, name)
                if rid is not None and rid not in keys["invoice_line_ids"]:
                    keys["invoice_line_ids"].append(rid)
            rid = extract_record_id(entry, "invoice_id")
            if rid is not None and rid not in keys["invoice_ids"]:
                keys["invoice_ids"].append(rid)
            rid = extract_record_id(entry, "customer_id")
            if rid is not None and rid not in keys["customer_ids"]:
                keys["customer_ids"].append(rid)
            rid = extract_record_id(entry, "item_id")
            if rid is not None and rid not in keys["item_ids"]:
                keys["item_ids"].append(rid)
    return keys


def quarantined_invoice_line_ids(run_id):
    """Backward-compatible invoice-line-only view of the quarantine keys."""
    return quarantined_keys(run_id)["invoice_line_ids"]
