"""Lazy dataset scale info (rows, months, size) from Parquet footers.

The values are read with DuckDB's ``parquet_file_metadata`` and
``parquet_metadata`` table functions. Both fetch only the Parquet footers
(row counts, file size, column statistics) and never scan data pages, so
this cannot OOM the app.

Reads happen lazily when the datasets table is rendered and the result is
cached in ``scenarios.manifest`` (JSONB) under the ``scale`` key, so each
scenario is measured once. A render never waits longer than
``SCALE_TIMEOUT_SECONDS``: on timeout or error the cell renders as an em
dash, and the background read keeps going for the next render.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone

from backend.config import settings
from backend.db.connection import execute

logger = logging.getLogger(__name__)

SCALE_TIMEOUT_SECONDS = 3.0
SCALE_KEY = "scale"
# Bump when the cached payload shape changes so stale caches recompute.
SCALE_VERSION = 1

_inflight: set[str] = set()
_inflight_lock = threading.Lock()


def scale_sql(source: str) -> str:
    """Footer-only SQL for one scenario's Parquet files.

    ``parquet_file_metadata`` supplies the exact row count and object size per
    file; ``parquet_metadata`` supplies the min/max of the ``period`` column
    statistics (month strings such as ``2024-01`` or first-of-month dates).
    """
    safe_source = str(source).replace("'", "''")
    uri = f"s3://{settings.r2_bucket}/scenarios/{safe_source}/*.parquet"
    return f"""
        WITH files AS (
            SELECT num_rows, file_size_bytes
            FROM parquet_file_metadata('{uri}')
        ),
        periods AS (
            SELECT
                min(left(coalesce(stats_min, stats_min_value), 7)) AS min_period,
                max(left(coalesce(stats_max, stats_max_value), 7)) AS max_period
            FROM parquet_metadata('{uri}')
            WHERE path_in_schema = 'period'
        )
        SELECT
            (SELECT sum(num_rows) FROM files) AS total_rows,
            (SELECT sum(file_size_bytes) FROM files) AS total_bytes,
            min_period,
            max_period
        FROM periods
    """


def _months_between(start, end) -> int | None:
    """Inclusive month count between two ``YYYY-MM`` boundaries."""
    try:
        start_year, start_month = (int(part) for part in str(start)[:7].split("-"))
        end_year, end_month = (int(part) for part in str(end)[:7].split("-"))
    except (TypeError, ValueError):
        return None
    months = (end_year - start_year) * 12 + (end_month - start_month) + 1
    return months if months > 0 else None


def format_rows(value) -> str | None:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return None


def format_months(value) -> str | None:
    try:
        return str(int(value))
    except (TypeError, ValueError):
        return None


def format_size(value) -> str | None:
    try:
        return f"{int(value) / 1_000_000:.1f} MB"
    except (TypeError, ValueError):
        return None


def cached_scale(manifest) -> dict | None:
    """Return the cached ``manifest.scale`` payload, if it is current."""
    if isinstance(manifest, str):
        try:
            manifest = json.loads(manifest)
        except (TypeError, ValueError):
            return None
    if not isinstance(manifest, dict):
        return None
    scale = manifest.get(SCALE_KEY)
    if not isinstance(scale, dict) or scale.get("version") != SCALE_VERSION:
        return None
    if scale.get("rows") is None:
        return None
    return scale


def read_scenario_scale(conn, source: str) -> dict | None:
    """Read one scenario's scale info from Parquet footers."""
    from backend.storage.duckdb_client import run_query_on

    cols, rows = run_query_on(conn, scale_sql(source))
    if not rows:
        return None
    row = dict(zip(cols, rows[0], strict=False))
    if row.get("total_rows") is None:
        return None
    return {
        "version": SCALE_VERSION,
        "scenario": source,
        "rows": int(row["total_rows"]),
        "months": _months_between(row.get("min_period"), row.get("max_period")),
        "size_bytes": int(row.get("total_bytes") or 0),
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


def _store(scenario: str, info: dict) -> None:
    """Merge the scale payload into ``scenarios.manifest`` (JSONB)."""
    execute(
        "UPDATE scenarios "
        "SET manifest = COALESCE(manifest, '{}'::jsonb) || jsonb_build_object(%s::text, %s::jsonb) "
        "WHERE name = %s",
        (SCALE_KEY, json.dumps(info), scenario),
    )


def _apply(scenario: dict, info: dict) -> None:
    scenario["rows"] = format_rows(info.get("rows"))
    scenario["months"] = format_months(info.get("months"))
    scenario["size"] = format_size(info.get("size_bytes"))


def _compute_and_cache(pending: list[dict], results: dict) -> None:
    """Background worker: read footers once per source, then cache each name."""
    names = [p["name"] for p in pending]
    conn = None
    try:
        from backend.storage.duckdb_client import open_connection

        conn = open_connection()
        # Footer reads are tiny (no data pages), so parallel file reads are
        # safe here: 16 parallel footer fetches finish in ~3s cold / <1s warm
        # instead of ~17s sequentially on a high-latency S3 endpoint.
        conn.execute("SET threads=16")
        by_source: dict[str, dict | None] = {}
        for item in pending:
            source = item["source"]
            if source not in by_source:
                try:
                    by_source[source] = read_scenario_scale(conn, source)
                except Exception as exc:  # S3/network/permission failures
                    logger.warning("Scale metadata read failed for %s: %s", source, exc)
                    by_source[source] = None
            info = by_source[source]
            if not info:
                continue
            try:
                _store(item["name"], info)
            except Exception as exc:  # keep rendering even if the cache write fails
                logger.warning("Scale cache write failed for %s: %s", item["name"], exc)
            results[item["name"]] = info
    except Exception as exc:
        logger.warning("Scale metadata computation failed: %s", exc)
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # pragma: no cover - defensive
                pass
        with _inflight_lock:
            _inflight.difference_update(names)


def attach_scale_info(scenarios: list[dict], timeout: float = SCALE_TIMEOUT_SECONDS) -> list[dict]:
    """Attach formatted ``rows`` / ``months`` / ``size`` to scenario dicts.

    Cached values are applied immediately. Uncached scenarios are measured in
    one background thread; the caller waits at most ``timeout`` seconds, so a
    slow or failing S3 read renders as an em dash instead of blocking a page.
    """
    pending: list[dict] = []
    for scenario in scenarios:
        scenario["rows"] = None
        scenario["months"] = None
        scenario["size"] = None
        source = scenario.get("source_scenario") or scenario.get("name")
        cached = cached_scale(scenario.get("manifest"))
        if cached and cached.get("scenario") in (None, source):
            _apply(scenario, cached)
            continue
        name = scenario.get("name")
        if name and source:
            pending.append({"name": name, "source": source})

    if not pending:
        return scenarios

    with _inflight_lock:
        todo = []
        for item in pending:
            if item["name"] in _inflight:
                continue
            _inflight.add(item["name"])
            todo.append(item)

    if not todo:
        return scenarios

    results: dict[str, dict] = {}
    worker = threading.Thread(
        target=_compute_and_cache,
        args=(todo, results),
        name="dataset-scale",
        daemon=True,
    )
    worker.start()
    worker.join(timeout)

    for scenario in scenarios:
        info = results.get(scenario.get("name"))
        if info:
            _apply(scenario, info)
    return scenarios
