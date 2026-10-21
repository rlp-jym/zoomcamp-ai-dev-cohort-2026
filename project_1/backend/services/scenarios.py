"""Scenario service (raw SQL over Postgres)."""

import json
from datetime import datetime

from backend.db.connection import fetch_all, fetch_one
from backend.storage.s3_client import list_scenario_keys


def _fmt_dt(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value)


def list_scenarios():
    rows = fetch_all(
        "SELECT name, status, seed, table_count, manifest, file_hashes, created_at "
        "FROM scenarios ORDER BY created_at DESC, name"
    )
    out = []
    for r in rows:
        out.append(
            {
                "name": r["name"],
                "status": r["status"],
                "tables": r["table_count"],
                "seed": r["seed"],
                "created_at": _fmt_dt(r["created_at"]).split(" ")[0] if r["created_at"] else "",
                "manifest": r["manifest"],
                "file_hashes": r["file_hashes"],
            }
        )
    return out


def list_analysis_scenarios():
    rows = fetch_all(
        "SELECT s.scenario_id, s.title, s.outcome, s.assessment, "
        "s.baseline_run, s.open_issues, s.source_anchor_type, s.source_anchor_id, s.created_at "
        "FROM analysis_scenarios s ORDER BY s.created_at DESC"
    )
    out = []
    for r in rows:
        out.append(
            {
                "scenario_id": str(r["scenario_id"]),
                "title": r["title"],
                "outcome": r["outcome"] or "",
                "assessment": r["assessment"] or "",
                "baseline_run": r["baseline_run"],
                "open_issues": r.get("open_issues"),
                "source_anchor_type": r.get("source_anchor_type"),
                "source_anchor_id": r.get("source_anchor_id"),
                "created_at": _fmt_dt(r["created_at"]),
            }
        )
    return out


def create_analysis_scenario(title, outcome, assessment, baseline_run="baseline_run",
                            source_anchor_type=None, source_anchor_id=None,
                            open_issues=None):
    if open_issues is None:
        try:
            from backend.services import exceptions as exc_svc
            open_issues = exc_svc.exception_counts().get("open")
        except Exception:
            open_issues = None
    row = fetch_one(
        """
        INSERT INTO analysis_scenarios (title, outcome, assessment, baseline_run,
                                       open_issues, source_anchor_type, source_anchor_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING scenario_id
        """,
        (title, outcome, assessment, baseline_run, open_issues,
         source_anchor_type, source_anchor_id),
    )
    return str(row["scenario_id"])


def get_source_messages(scenario):
    """Return the originating dashboard thread messages, if any."""
    if not scenario:
        return []
    at = scenario.get("source_anchor_type")
    aid = scenario.get("source_anchor_id")
    if not at or not aid:
        return []
    from backend.services import messages as msg_svc
    return msg_svc.get_messages(at, aid)


def get_analysis_scenario(scenario_id):
    r = fetch_one(
        "SELECT scenario_id, title, outcome, assessment, baseline_run, "
        "open_issues, source_anchor_type, source_anchor_id, created_at "
        "FROM analysis_scenarios WHERE scenario_id = %s",
        (scenario_id,),
    )
    if not r:
        return None
    return {
        "scenario_id": str(r["scenario_id"]),
        "title": r["title"],
        "outcome": r["outcome"],
        "assessment": r["assessment"],
        "baseline_run": r["baseline_run"],
        "open_issues": r.get("open_issues"),
        "source_anchor_type": r.get("source_anchor_type"),
        "source_anchor_id": r.get("source_anchor_id"),
        "created_at": _fmt_dt(r["created_at"]),
    }


def get_scenario(name):
    r = fetch_one(
        "SELECT name, status, seed, table_count, manifest, file_hashes, created_at "
        "FROM scenarios WHERE name = %s",
        (name,),
    )
    if not r:
        return None
    return {
        "name": r["name"],
        "status": r["status"],
        "tables": r["table_count"],
        "seed": r["seed"],
        "created_at": _fmt_dt(r["created_at"]),
        "manifest": r["manifest"],
        "file_hashes": r["file_hashes"],
    }


def register_scenario(payload):
    payload = payload or {}
    name = payload.get("name") or payload.get("scenario_name") or payload.get("scenario")
    if not name:
        raise ValueError("scenario name is required")
    seed = payload.get("seed")
    try:
        seed = int(seed) if seed is not None and seed != "" else None
    except (TypeError, ValueError):
        seed = None
    manifest = payload.get("manifest")
    file_hashes = payload.get("file_hashes")
    table_count = payload.get("table_count")
    if table_count is None and isinstance(manifest, dict):
        table_count = len(manifest.get("tables", {}))
    if table_count is None:
        table_count = 0
    try:
        table_count = int(table_count)
    except (TypeError, ValueError):
        table_count = 0
    status = payload.get("status") or "registered"

    row = fetch_one(
        """
        INSERT INTO scenarios (name, status, seed, table_count, manifest, file_hashes, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, now())
        ON CONFLICT (name) DO UPDATE SET
            status = EXCLUDED.status,
            seed = COALESCE(EXCLUDED.seed, scenarios.seed),
            table_count = EXCLUDED.table_count,
            manifest = COALESCE(EXCLUDED.manifest, scenarios.manifest),
            file_hashes = COALESCE(EXCLUDED.file_hashes, scenarios.file_hashes),
            updated_at = now()
        RETURNING name
        """,
        (name, status, seed, table_count, json.dumps(manifest) if manifest is not None else None,
         json.dumps(file_hashes) if file_hashes is not None else None),
    )
    return get_scenario(name)


def ensure_baseline_registered():
    if get_scenario("baseline_run"):
        return get_scenario("baseline_run")
    keys = list_scenario_keys("baseline_run")
    if not keys:
        return None
    return register_scenario(
        {
            "name": "baseline_run",
            "seed": 9,
            "status": "registered",
            "table_count": 16,
        }
    )
