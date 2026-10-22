"""Scenario service (raw SQL over Postgres)."""

import json
from datetime import datetime

from backend.db.connection import execute, fetch_all, fetch_one
from backend.storage.s3_client import list_scenario_keys


def _fmt_dt(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %I:%M:%S %p")
    return str(value)


def list_scenarios():
    rows = fetch_all(
        "SELECT name, status, seed, table_count, manifest, file_hashes, source_scenario, created_at "
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
                "source_scenario": r.get("source_scenario") or r["name"],
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
                            open_issues=None, baseline_snapshot=None):
    if open_issues is None:
        try:
            from backend.services import exceptions as exc_svc
            open_issues = exc_svc.exception_counts().get("open")
        except Exception:
            open_issues = None
    if baseline_snapshot is None:
        try:
            from backend.services import dashboard as dash_svc
            data, _ = dash_svc.get_from_cache()
            if data and data.get("available"):
                chart = (data.get("charts") or {}).get("revenue_plan", {})
                labels = chart.get("labels") or []
                actual = chart.get("actual") or []
                billings = chart.get("billings") or []
                budget = chart.get("budget") or []
                n = min(6, len(labels))
                baseline_snapshot = {
                    "run_id": data.get("published_run"),
                    "months": labels[-n:],
                    "actual": actual[-n:],
                    "billings": billings[-n:],
                    "budget": budget[-n:],
                }
        except Exception:
            baseline_snapshot = None
    row = fetch_one(
        """
        INSERT INTO analysis_scenarios (title, outcome, assessment, baseline_run,
                                       open_issues, source_anchor_type, source_anchor_id,
                                       baseline_snapshot)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING scenario_id
        """,
        (title, outcome, assessment, baseline_run, open_issues,
         source_anchor_type, source_anchor_id,
         json.dumps(baseline_snapshot) if baseline_snapshot is not None else None),
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
        "open_issues, source_anchor_type, source_anchor_id, baseline_snapshot, created_at "
        "FROM analysis_scenarios WHERE scenario_id = %s",
        (scenario_id,),
    )
    if not r:
        return None
    snapshot = r.get("baseline_snapshot")
    if isinstance(snapshot, str):
        try:
            snapshot = json.loads(snapshot)
        except Exception:
            pass
    return {
        "scenario_id": str(r["scenario_id"]),
        "title": r["title"],
        "outcome": r["outcome"],
        "assessment": r["assessment"],
        "baseline_run": r["baseline_run"],
        "open_issues": r.get("open_issues"),
        "source_anchor_type": r.get("source_anchor_type"),
        "source_anchor_id": r.get("source_anchor_id"),
        "baseline_snapshot": snapshot,
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


def delete_scenario(name):
    execute("DELETE FROM scenarios WHERE name = %s", (name,))


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
    status = "ready"

    fetch_one(
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


def delete_analysis_scenario(scenario_id):
    from backend.services import messages as msg_svc

    sid = str(scenario_id)
    try:
        did = msg_svc._ensure_discussion("analysis", sid)
        execute("DELETE FROM messages WHERE discussion_id = %s", (did,))
        execute("DELETE FROM discussions WHERE discussion_id = %s", (did,))
    except Exception:
        pass
    execute("DELETE FROM analysis_scenarios WHERE scenario_id = %s", (scenario_id,))


def import_thread_messages(target_scenario_id, source_anchor_type, source_anchor_id,
                           from_date=None, to_date=None):
    from backend.services import messages as msg_svc

    src_msgs = msg_svc.get_messages(source_anchor_type, source_anchor_id)
    filtered = []
    for m in src_msgs:
        created = m.get("created_at") or ""
        if from_date and created < from_date:
            continue
        if to_date and created > to_date + " 23:59:59":
            continue
        filtered.append(m)

    target_did = msg_svc._ensure_discussion("analysis", str(target_scenario_id))
    count = 0
    for m in filtered:
        execute(
            "INSERT INTO messages (discussion_id, persona_id, content, created_at) "
            "VALUES (%s, %s, %s, %s)",
            (target_did, m.get("persona_id"), m.get("content"), m.get("created_at")),
        )
        count += 1
    return count


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
