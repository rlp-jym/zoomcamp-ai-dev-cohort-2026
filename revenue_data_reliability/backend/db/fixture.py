"""Idempotent baseline fixture seeder.

Ensures a minimal baseline_run fixture exists in Postgres so the dashboard
is usable immediately after boot/reset without requiring a full pipeline run.
"""
import json
import os
from datetime import datetime, timezone

from backend.db.connection import execute, fetch_one

BASELINE = "baseline_run"
BASELINE_TRACE = "fixture-baseline-trace"


def _ensure_scenario():
    row = fetch_one("SELECT name FROM scenarios WHERE name = %s", (BASELINE,))
    if row:
        return
    execute(
        """
        INSERT INTO scenarios (name, status, seed, table_count, updated_at)
        VALUES (%s, %s, %s, %s, now())
        ON CONFLICT (name) DO NOTHING
        """,
        (BASELINE, "registered", 9, 16),
    )


def _ensure_baseline_run():
    row = fetch_one("SELECT run_id FROM runs WHERE scenario_name = %s", (BASELINE,))
    if row:
        return row["run_id"]
    run_id_row = fetch_one(
        """
        INSERT INTO runs (scenario_name, status, triggered_by, trace_id,
                          started_at, finished_at, duration,
                          validations_total, validations_failed, exceptions_created,
                          published, published_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING run_id
        """,
        (
            BASELINE,
            "completed",
            "fixture",
            BASELINE_TRACE,
            datetime.now(timezone.utc),
            datetime.now(timezone.utc),
            "0s",
            0,
            0,
            0,
            True,
            datetime.now(timezone.utc),
        ),
    )
    return run_id_row["run_id"]


def _ensure_publication(run_id: int):
    row = fetch_one("SELECT publication_id FROM publications WHERE run_id = %s", (run_id,))
    if row:
        return
    execute(
        """
        INSERT INTO publications (run_id, published_by, pointer)
        VALUES (%s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        (run_id, "manager", f"scenarios/{BASELINE}"),
    )


def _ensure_discussion(run_id: int):
    did = fetch_one(
        "SELECT discussion_id FROM discussions WHERE anchor_type='run' AND anchor_id=%s",
        (str(run_id),),
    )
    if did:
        return
    did_row = fetch_one(
        """
        INSERT INTO discussions (anchor_type, anchor_id, title)
        VALUES ('run', %s, %s)
        RETURNING discussion_id
        """,
        (str(run_id), "Baseline run (fixture)"),
    )
    discussion_id = did_row["discussion_id"] if did_row else None
    if not discussion_id:
        return
    execute(
        """
        INSERT INTO messages (discussion_id, persona_id, content, trace_id, evidence)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (
            discussion_id,
            "orchestrator",
            "Baseline run bootstrapped as published fixture (no pipeline execution).",
            BASELINE_TRACE,
            json.dumps({"fixture": True}),
        ),
    )


def ensure_baseline_fixture() -> None:
    if os.getenv("SEED_BASELINE_FIXTURE", "1") == "0":
        return
    _ensure_scenario()
    run_id = _ensure_baseline_run()
    _ensure_publication(run_id)
    _ensure_discussion(run_id)