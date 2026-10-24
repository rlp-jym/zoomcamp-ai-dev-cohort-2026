"""One-time database cleanup for the retired baseline dataset.

Deletes a dataset row (``baseline_run`` by default) together with every row
derived from its validation runs: exceptions, discussions/messages,
quarantines, publications, approvals, alerts, and telemetry.

S3/Filebase is intentionally untouched. Each live dataset owns its own
``datasets.s3_prefix``; this script never touches any Parquet object.

Usage (dry run by default)::

    python -m backend.db.cleanup
    python -m backend.db.cleanup --apply
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass

from backend.db.connection import close_pool, get_connection, init_pool

BASELINE_DATASET = "baseline_run"

_ANCHOR_PREDICATE = """
    (
        (anchor_type = 'run' AND anchor_id = ANY(%s))
        OR (anchor_type = 'exception' AND anchor_id = ANY(%s))
    )
"""

_APPROVAL_PREDICATE = """
    (
        (target_type = 'run' AND target_id = ANY(%s))
        OR (target_type = 'exception' AND target_id = ANY(%s))
    )
"""


@dataclass
class CleanupSummary:
    dataset: str
    applied: bool
    runs: int
    exceptions: int
    validations: int
    reconciliations: int
    quarantines: int
    publications: int
    discussions: int
    messages: int
    approvals: int
    alerts: int
    agent_actions: int
    otel_spans: int
    otel_logs: int
    dashboard_cache: int
    datasets: int


def _fetch_ids(cur, sql, params=()):
    cur.execute(sql, params)
    return [row[0] for row in cur.fetchall()]


def _count(cur, sql, params=()) -> int:
    cur.execute(sql, params)
    row = cur.fetchone()
    return int(row[0]) if row else 0


def _delete(cur, sql, params=()) -> int:
    cur.execute(sql, params)
    return int(cur.rowcount or 0)


def _scope(cur, dataset_name: str):
    run_ids = _fetch_ids(
        cur, "SELECT run_id FROM runs WHERE dataset_name = %s", (dataset_name,)
    )
    exception_ids = (
        _fetch_ids(
            cur, "SELECT exception_id FROM exceptions WHERE run_id = ANY(%s)", (run_ids,)
        )
        if run_ids
        else []
    )
    trace_ids = (
        _fetch_ids(cur, "SELECT trace_id FROM runs WHERE run_id = ANY(%s)", (run_ids,))
        if run_ids
        else []
    )
    trace_ids = [value for value in trace_ids if value]
    return run_ids, exception_ids, trace_ids


def cleanup_dataset(dataset_name: str = BASELINE_DATASET, apply: bool = False) -> dict:
    """Delete *dataset_name* and everything derived from its runs.

    Returns a JSON-serializable summary of affected rows. When ``apply`` is
    false nothing is deleted; the same queries are counted instead.
    """
    with get_connection() as conn:
        with conn.cursor() as cur:
            run_ids, exception_ids, trace_ids = _scope(cur, dataset_name)
            run_text_ids = [str(value) for value in run_ids]
            exception_text_ids = [str(value) for value in exception_ids]
            anchor_params = (run_text_ids, exception_text_ids)

            statements = [
                (
                    "messages",
                    "DELETE FROM messages WHERE discussion_id IN "
                    f"(SELECT discussion_id FROM discussions WHERE {_ANCHOR_PREDICATE})",
                    anchor_params,
                ),
                (
                    "discussions",
                    f"DELETE FROM discussions WHERE {_ANCHOR_PREDICATE}",
                    anchor_params,
                ),
                (
                    "agent_actions",
                    f"DELETE FROM agent_actions WHERE {_ANCHOR_PREDICATE}",
                    anchor_params,
                ),
                (
                    "alerts",
                    f"DELETE FROM alerts WHERE {_ANCHOR_PREDICATE}",
                    anchor_params,
                ),
                (
                    "approvals",
                    f"DELETE FROM approvals WHERE {_APPROVAL_PREDICATE}",
                    anchor_params,
                ),
                (
                    "quarantines",
                    "DELETE FROM quarantines "
                    "WHERE run_id = ANY(%s) OR exception_id = ANY(%s)",
                    (run_ids, exception_ids),
                ),
                (
                    "validations",
                    "DELETE FROM validations WHERE run_id = ANY(%s)",
                    (run_ids,),
                ),
                (
                    "exceptions",
                    "DELETE FROM exceptions WHERE run_id = ANY(%s)",
                    (run_ids,),
                ),
                (
                    "reconciliations",
                    "DELETE FROM reconciliations WHERE run_id = ANY(%s)",
                    (run_ids,),
                ),
                (
                    "publications",
                    "DELETE FROM publications WHERE run_id = ANY(%s)",
                    (run_ids,),
                ),
                (
                    "otel_spans",
                    "DELETE FROM otel_spans WHERE trace_id = ANY(%s)",
                    (trace_ids,),
                ),
                (
                    "otel_logs",
                    "DELETE FROM otel_logs WHERE trace_id = ANY(%s)",
                    (trace_ids,),
                ),
                (
                    "runs",
                    "DELETE FROM runs WHERE dataset_name = %s",
                    (dataset_name,),
                ),
                (
                    "dashboard_cache",
                    "DELETE FROM dashboard_cache "
                    "WHERE dataset_name = %s OR cache_key = %s",
                    (dataset_name, f"dashboard:{dataset_name}"),
                ),
                (
                    "datasets",
                    "DELETE FROM datasets WHERE name = %s",
                    (dataset_name,),
                ),
            ]

            counts = {}
            for name, delete_sql, params in statements:
                count_sql = delete_sql.replace("DELETE FROM", "SELECT COUNT(*) FROM", 1)
                counts[name] = _count(cur, count_sql, params)

            if apply:
                deleted = {}
                for name, delete_sql, params in statements:
                    deleted[name] = _delete(cur, delete_sql, params)
                counts = deleted

        if apply:
            conn.commit()
        else:
            conn.rollback()

    counts["dataset"] = dataset_name
    counts["applied"] = apply
    return asdict(CleanupSummary(**counts))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        default=BASELINE_DATASET,
        help=f"Dataset to remove (default: {BASELINE_DATASET})",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Delete the rows. Without this flag the script is a dry run.",
    )
    args = parser.parse_args(argv)

    init_pool()
    try:
        summary = cleanup_dataset(args.dataset, apply=args.apply)
    finally:
        close_pool()

    print(json.dumps(summary, indent=2))
    if not args.apply:
        print("\nDry run only. Re-run with --apply to delete these rows.")
    print("\nS3/Filebase Parquet files were NOT modified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
