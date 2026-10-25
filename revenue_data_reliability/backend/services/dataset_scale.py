"""Lazy dataset scale info (rows, months, size) from Parquet footers.

The values are read with DuckDB's ``parquet_file_metadata`` and
``parquet_metadata`` table functions. Both fetch only the Parquet footers
(row counts, file size, column statistics) and never scan data pages, so
this cannot OOM the app.

Generated ("fast demo") scenarios are clones that share the baseline files in
S3, but they promise a shorter history (``years_to_backtrack``). The footer
gives the full source period span; the requested window is the trailing
``Y`` years ending in the last completed month. Files whose period range does
not intersect that window are excluded. Because the fixture writes one
file per table (all months in each file) rather than one file per period, the
remaining totals are adjusted by the intersecting month share so a y1 clone
does not report the y5 row/byte count.

Reads happen lazily when the datasets table is rendered and the result is
cached in ``datasets.manifest`` (JSONB) under the ``scale`` key, so each
scenario is measured once. A render never waits longer than
``SCALE_TIMEOUT_SECONDS``: on timeout or error the cell renders as an em
dash, and the background read keeps going for the next render.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from datetime import date, datetime, timedelta, timezone

from backend.config import settings
from backend.db.connection import execute
from backend.storage.s3_client import prefix_folder

logger = logging.getLogger(__name__)

SCALE_TIMEOUT_SECONDS = 3.0
SCALE_KEY = "scale"
# Bump when the cached payload shape changes so stale caches recompute.
SCALE_VERSION = 3

_YEARS_RE = re.compile(r"_y(\d+)$")

_inflight: set[str] = set()
_inflight_lock = threading.Lock()


def parse_years_to_backtrack(name) -> int | None:
    """Read the ``Y`` in a ``generated_seed{X}_y{Y}`` scenario name."""
    match = _YEARS_RE.search(str(name or ""))
    if not match:
        return None
    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def _previous_month_end() -> tuple[int, int]:
    """Year and month of the last completed month."""
    today = date.today()
    previous = today.replace(day=1) - timedelta(days=1)
    return previous.year, previous.month


def scale_window(years: int) -> tuple[str, str]:
    """Trailing period window for a scenario with ``years`` years of history.

    The generator ends its timeline at the previous completed month, so the
    window has to trail today rather than snap to calendar years.
    """
    end_year, end_month = _previous_month_end()
    months_back = int(years) * 12 - 1
    start_year, start_month0 = divmod(
        end_year * 12 + (end_month - 1) - months_back, 12
    )
    return f"{start_year:04d}-{start_month0 + 1:02d}", f"{end_year:04d}-{end_month:02d}"


def scale_sql(source: str, years: int | None = None) -> str:
    """Footer-only SQL for one scenario's Parquet files.

    ``parquet_file_metadata`` supplies the exact row count and object size per
    file; ``parquet_metadata`` supplies each file's ``period`` column range
    from its footer statistics. Rows/bytes are summed only for files whose
    period range intersects the requested window (files without a ``period``
    column, e.g. dimensions, are always included).
    """
    safe_source = str(source).replace("'", "''")
    uri = f"s3://{settings.r2_bucket}/scenarios/{safe_source}/*.parquet"
    if years:
        window_start, window_end = scale_window(years)
        intersects = (
            "(p.min_period IS NULL OR "
            f"(p.max_period >= '{window_start}' AND p.min_period <= '{window_end}'))"
        )
    else:
        intersects = "TRUE"
    return f"""
        WITH files AS (
            SELECT file_name, num_rows, file_size_bytes
            FROM parquet_file_metadata('{uri}')
        ),
        periods AS (
            SELECT
                file_name,
                min(left(coalesce(stats_min, stats_min_value), 7)) AS min_period,
                max(left(coalesce(stats_max, stats_max_value), 7)) AS max_period
            FROM parquet_metadata('{uri}')
            WHERE path_in_schema = 'period'
            GROUP BY file_name
        )
        SELECT
            sum(f.num_rows) FILTER (WHERE {intersects}) AS total_rows,
            sum(f.file_size_bytes) FILTER (WHERE {intersects}) AS total_bytes,
            min(p.min_period) FILTER (WHERE {intersects}) AS source_min_period,
            max(p.max_period) FILTER (WHERE {intersects}) AS source_max_period
        FROM files f
        LEFT JOIN periods p USING (file_name)
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


def windowed_scale(total_rows, total_bytes, source_min, source_max, years: int | None) -> dict:
    """Adjust source-wide footer totals to the requested history window.

    ``total_rows``/``total_bytes`` already cover only files whose period range
    intersects the window. When those files hold more months than the window
    (one file per table, all months in each), the totals are scaled by the
    intersecting share so ``y1`` reports roughly a fifth of a 60-month source.
    """
    try:
        rows = int(total_rows or 0)
        size = int(total_bytes or 0)
    except (TypeError, ValueError):
        rows, size = 0, 0
    source_months = _months_between(source_min, source_max)
    months = source_months
    if years:
        window_start, window_end = scale_window(years)
        if source_min and source_max:
            start = max(str(source_min)[:7], window_start)
            end = min(str(source_max)[:7], window_end)
            intersect_months = _months_between(start, end) or 0
            months = intersect_months
            if source_months and 0 < intersect_months < source_months:
                share = intersect_months / source_months
                rows = round(rows * share)
                size = round(size * share)
        else:
            months = int(years) * 12
    return {"rows": rows, "months": months, "size_bytes": size}


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


def read_scenario_scale(conn, source: str, years: int | None = None) -> dict | None:
    """Read one scenario's scale info from Parquet footers."""
    from backend.storage.duckdb_client import run_query_on

    cols, rows = run_query_on(conn, scale_sql(source, years))
    if not rows:
        return None
    row = dict(zip(cols, rows[0], strict=False))
    if row.get("total_rows") is None:
        return None
    scale = windowed_scale(
        row.get("total_rows"),
        row.get("total_bytes"),
        row.get("source_min_period"),
        row.get("source_max_period"),
        years,
    )
    return {
        "version": SCALE_VERSION,
        "scenario": source,
        "years_to_backtrack": int(years) if years else None,
        "rows": scale["rows"],
        "months": scale["months"],
        "size_bytes": scale["size_bytes"],
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


def _store(scenario: str, info: dict) -> None:
    """Merge the scale payload into ``datasets.manifest`` (JSONB)."""
    execute(
        "UPDATE datasets "
        "SET manifest = COALESCE(manifest, '{}'::jsonb) || jsonb_build_object(%s::text, %s::jsonb) "
        "WHERE name = %s",
        (SCALE_KEY, json.dumps(info), scenario),
    )


def _apply(scenario: dict, info: dict) -> None:
    scenario["rows"] = format_rows(info.get("rows"))
    scenario["months"] = format_months(info.get("months"))
    scenario["size"] = format_size(info.get("size_bytes"))


def _compute_and_cache(pending: list[dict], results: dict) -> None:
    """Background worker: read footers once per (source, years), then cache."""
    names = [p["name"] for p in pending]
    conn = None
    try:
        from backend.storage.duckdb_client import open_connection

        conn = open_connection()
        # Footer reads are tiny (no data pages) and run in a short-lived
        # connection, but keep the thread count aligned with the container-wide
        # single-thread ceiling.
        conn.execute("SET threads=1")
        conn.execute("SET memory_limit='100MB'")
        by_key: dict[tuple[str, int | None], dict | None] = {}
        for item in pending:
            key = (item["source"], item.get("years"))
            if key not in by_key:
                try:
                    by_key[key] = read_scenario_scale(conn, item["source"], item.get("years"))
                except Exception as exc:  # S3/network/permission failures
                    logger.warning("Scale metadata read failed for %s: %s", item["source"], exc)
                    by_key[key] = None
            info = by_key[key]
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


def resolve_years(scenario: dict) -> int | None:
    """Scenario column first, then the ``_y{Y}`` suffix on its name."""
    years = scenario.get("years_to_backtrack")
    if years is not None:
        try:
            return int(years)
        except (TypeError, ValueError):
            pass
    return parse_years_to_backtrack(scenario.get("name"))


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
        source = prefix_folder(scenario.get("s3_prefix") or "") or (
            scenario.get("source_dataset")
            or scenario.get("source_scenario")
            or scenario.get("name")
        )
        years = resolve_years(scenario)
        cached = cached_scale(scenario.get("manifest"))
        if cached and cached.get("scenario") in (None, source) and cached.get("years_to_backtrack") == years:
            _apply(scenario, cached)
            continue
        name = scenario.get("name")
        if name and source:
            pending.append({"name": name, "source": source, "years": years})

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
