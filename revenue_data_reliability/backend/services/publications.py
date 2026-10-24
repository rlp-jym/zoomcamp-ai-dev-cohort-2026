"""Publication service: go-live pointer + published-data query.

Publications record the Manager's go-live decision. The published data
itself is derived at query time: the scenario's Parquet files are read
from S3 (Filebase) with quarantine rows applied as an exclusion filter.
(Per SPEC §4, the parquet bundle is per scenario, so the published run
selects *which* bundle version and which quarantines apply.)
"""


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


def get_published_run(dataset_name):
    """The run currently holding the published pointer for a dataset."""
    r = fetch_one(
        """
        SELECT * FROM runs
        WHERE dataset_name = %s AND published = TRUE
        ORDER BY published_at DESC, run_id DESC
        LIMIT 1
        """,
        (dataset_name,),
    )
    if not r:
        return None
    return {
        "id": r["run_id"],
        "dataset": r["dataset_name"],
        "scenario": r["dataset_name"],
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

    dataset_name = run.get("dataset") or run.get("scenario")
    # Move the published pointer: exactly one published run per dataset.
    if dataset_name:
        execute(
            """
            UPDATE runs
            SET published = FALSE, published_at = NULL
            WHERE dataset_name = %s AND run_id <> %s
            """,
            (dataset_name, run_id),
        )
    execute(
        "UPDATE runs SET published = TRUE, published_at = now() WHERE run_id = %s",
        (run_id,),
    )
    pointer = f"scenarios/{dataset_name}" if dataset_name else f"runs/{run_id}"
    row = fetch_one(
        """
        INSERT INTO publications (run_id, published_by, pointer)
        VALUES (%s, %s, %s)
        RETURNING publication_id, published_at
        """,
        (run_id, persona_id, pointer),
    )
    from backend.services import dashboard as dashboard_svc
    dashboard_svc.invalidate_dashboard_cache()
    return {
        "publication_id": row["publication_id"],
        "run_id": run_id,
        "published_by": persona_id,
        "pointer": pointer,
        "published_at": str(row["published_at"]),
        "created": True,
    }


def _table_uri(dataset_name, table):
    from backend.storage.s3_client import dataset_s3_prefix

    prefix = dataset_s3_prefix(dataset_name)
    return f"s3://{settings.r2_bucket}/{prefix}{table}.parquet"


def _int_list(values):
    return ", ".join(str(int(value)) for value in values)


def get_published_data_query(dataset_name):
    """Build the published-data query for a dataset.

    Reads the dataset's Parquet invoice lines from S3 (Filebase) and
    excludes every record quarantined for the published run. Quarantine
    identifiers are typed, so invoice-, customer-, and item-level quarantine
    rows now remove the affected invoice lines too. Returns a dict with the
    DuckDB SQL, the published run id, the excluded ids, and the typed
    quarantine keys used by the dashboard's GL/budget/customer filters.
    """
    run = get_published_run(dataset_name)
    if not run:
        return None
    keys = quarantines_svc.quarantined_keys(run["id"])
    predicates = []
    if keys["invoice_line_ids"]:
        predicates.append(
            f"il.invoice_line_id NOT IN ({_int_list(keys['invoice_line_ids'])})"
        )
    if keys["invoice_ids"]:
        predicates.append(
            f"il.invoice_id NOT IN ({_int_list(keys['invoice_ids'])})"
        )
    if keys["item_ids"]:
        predicates.append(
            f"il.item_id NOT IN ({_int_list(keys['item_ids'])})"
        )
    if keys["customer_ids"]:
        predicates.append(
            "il.invoice_id NOT IN ("
            f"SELECT invoice_id FROM read_parquet('{_table_uri(dataset_name, 'invoices')}') "
            f"WHERE customer_id IN ({_int_list(keys['customer_ids'])}))"
        )
    sql = f"SELECT * FROM read_parquet('{_table_uri(dataset_name, 'invoice_lines')}') il"
    if predicates:
        sql += " WHERE " + " AND ".join(predicates)
    return {
        "run_id": run["id"],
        "dataset": dataset_name,
        "dataset_name": dataset_name,
        "scenario": dataset_name,
        "sql": sql,
        "quarantined_ids": keys["invoice_line_ids"],
        "quarantine_keys": keys,
    }


def get_published_invoice_lines(dataset_name):
    """Execute the published-data query; returns rows without quarantined records."""
    query = get_published_data_query(dataset_name)
    if not query:
        return []
    from backend.storage.duckdb_client import query_rows
    return query_rows(query["sql"])
