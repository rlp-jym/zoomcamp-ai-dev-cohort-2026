"""Publication service: go-live pointer + published-data query.

Publications record the Manager's go-live decision. The published data
itself is derived at query time: the scenario's Parquet files are read
from S3 (Filebase) with quarantine rows applied as an exclusion filter.
(Per SPEC §4, the parquet bundle is per scenario, so the published run
selects *which* bundle version and which quarantines apply.)
"""

import json

from backend.config import settings
from backend.db.connection import execute, fetch_all, fetch_one
from backend.services import quarantines as quarantines_svc
from backend.services import runs as runs_svc


def get_publication_for_run(run_id):
    r = fetch_one(
        """
        SELECT * FROM publications
        WHERE run_id = %s
        ORDER BY publication_id DESC
        LIMIT 1
        """,
        (run_id,),
    )
    if not r:
        return None
    return {
        "publication_id": r["publication_id"],
        "run_id": r["run_id"],
        "published_by": r["published_by"],
        "pointer": r["pointer"],
        "published_at": str(r["published_at"]),
        "created_at": str(r["created_at"]),
    }


def get_publications():
    """All publications, newest first (used by audit later)."""
    rows = fetch_all(
        "SELECT * FROM publications ORDER BY publication_id DESC"
    )
    return [
        {
            "id": r["publication_id"],
            "run_id": r["run_id"],
            "published_by": r["published_by"],
            "pointer": r["pointer"],
            "published_at": str(r["published_at"]),
        }
        for r in rows
    ]


def get_published_run(scenario_name):
    """The run currently holding the published pointer for a scenario."""
    r = fetch_one(
        """
        SELECT * FROM runs
        WHERE scenario_name = %s AND published = TRUE
        ORDER BY published_at DESC, run_id DESC
        LIMIT 1
        """,
        (scenario_name,),
    )
    if not r:
        return None
    return {
        "id": r["run_id"],
        "scenario": r["scenario_name"],
        "status": r["status"],
        "trace_id": r["trace_id"],
        "published_at": str(r["published_at"]),
    }


def publish_run(run_id, persona_id, trace_id=None, comment=None):
    """Approve go-live for a run: publication row + published pointer.

    Idempotent: publishing an already-published run returns the existing
    publication instead of creating a duplicate row.

    Returns {"publication_id", "pointer", "published_at", "created"}.
    """
    run = runs_svc.get_run(run_id)
    if not run:
        raise ValueError(f"run {run_id} not found")

    existing = get_publication_for_run(run_id)
    if existing:
        return {**existing, "created": False}

    # Approval audit trail (same gate as remediation approvals).
    runs_svc.approve_run(run_id, persona_id, trace_id, comment)

    # Move the published pointer: exactly one published run per scenario.
    if run["scenario"]:
        execute(
            """
            UPDATE runs
            SET published = FALSE, published_at = NULL
            WHERE scenario_name = %s AND run_id <> %s
            """,
            (run["scenario"], run_id),
        )
    execute(
        "UPDATE runs SET published = TRUE, published_at = now() WHERE run_id = %s",
        (run_id,),
    )
    pointer = f"scenarios/{run['scenario']}" if run["scenario"] else f"runs/{run_id}"
    row = fetch_one(
        """
        INSERT INTO publications (run_id, published_by, pointer)
        VALUES (%s, %s, %s)
        RETURNING publication_id, published_at
        """,
        (run_id, persona_id, pointer),
    )
    return {
        "publication_id": row["publication_id"],
        "run_id": run_id,
        "published_by": persona_id,
        "pointer": pointer,
        "published_at": str(row["published_at"]),
        "created": True,
    }


def _invoice_lines_uri(scenario_name):
    return (
        f"s3://{settings.r2_bucket}/scenarios/{scenario_name}/invoice_lines.parquet"
    )


def get_published_data_query(scenario_name):
    """Build the published-data query for a scenario.

    Reads the scenario's Parquet invoice lines from S3 (Filebase) and
    excludes every record quarantined for the published run. Returns a
    dict with the DuckDB SQL, the published run id, and the excluded
    invoice line ids. Phase 3 (dashboard KPIs) executes this query.
    """
    run = get_published_run(scenario_name)
    if not run:
        return None
    excluded = quarantines_svc.quarantined_invoice_line_ids(run["id"])
    sql = f"SELECT * FROM read_parquet('{_invoice_lines_uri(scenario_name)}') il"
    if excluded:
        id_list = ", ".join(str(int(i)) for i in excluded)
        sql += f" WHERE il.invoice_line_id NOT IN ({id_list})"
    return {
        "run_id": run["id"],
        "scenario": scenario_name,
        "sql": sql,
        "quarantined_ids": excluded,
    }


def get_published_invoice_lines(scenario_name):
    """Execute the published-data query; returns rows without quarantined records."""
    query = get_published_data_query(scenario_name)
    if not query:
        return []
    from backend.storage.duckdb_client import query_rows
    return query_rows(query["sql"])
