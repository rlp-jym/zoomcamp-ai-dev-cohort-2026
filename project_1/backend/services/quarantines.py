"""Quarantine service (raw SQL over Postgres).

A quarantine row excludes records from the published view for a run.
``record_keys`` holds the affected record identifiers (e.g. invoice line
ids captured from the exception details or validation samples).
"""

import json

from backend.db.connection import execute, fetch_all, fetch_one


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
        "record_keys": json.loads(r["record_keys"]) if isinstance(r["record_keys"], str) else r["record_keys"],
        "created_by": r["created_by"],
        "created_at": str(r["created_at"]),
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


def extract_record_id(entry):
    """Best-effort extraction of an invoice line id from a record entry."""
    if isinstance(entry, dict):
        for key in ("invoice_line_id", "line_id", "record_key"):
            value = entry.get(key)
            if value is not None:
                entry = value
                break
        else:
            return None
    try:
        return int(entry)
    except (TypeError, ValueError):
        return None


def quarantined_invoice_line_ids(run_id):
    """Flatten all quarantined record keys for a run into invoice line ids."""
    rows = fetch_all(
        "SELECT record_keys FROM quarantines WHERE run_id = %s",
        (run_id,),
    )
    ids = []
    for r in rows:
        for entry in _iter_key_entries(r["record_keys"]):
            rid = extract_record_id(entry)
            if rid is not None and rid not in ids:
                ids.append(rid)
    return ids
