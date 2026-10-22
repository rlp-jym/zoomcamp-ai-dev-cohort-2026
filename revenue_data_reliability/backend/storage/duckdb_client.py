"""DuckDB connection with httpfs for reading Parquet from S3.

DuckDB has no OTEL auto-instrumentor, so every query batch is wrapped in a
manual span (``duckdb.query``) with the statement recorded, which keeps the
span tree readable in ``/observability`` without leaking credentials (the
S3 connection ``SET`` commands are never traced).
"""

import os
import tempfile
import threading
import uuid
from pathlib import Path
from urllib.parse import urlparse

import duckdb
from opentelemetry import trace

from backend.config import settings

_TRACER = trace.get_tracer("backend.duckdb")
_temp_state = threading.local()


def _temp_directory() -> str:
    """Return a thread-local DuckDB spill directory.

    Concurrent DuckDB connections otherwise share the default ``.tmp`` folder
    and can race while deleting spill files.  One directory per thread keeps
    the pipeline and the dashboard scheduler isolated.
    """
    path = getattr(_temp_state, "path", None)
    if path is None:
        root = Path(tempfile.gettempdir()) / "revenue_duckdb"
        path = root / f"{os.getpid()}-{uuid.uuid4().hex}"
        path.mkdir(parents=True, exist_ok=True)
        _temp_state.path = path
    return path.as_posix()


def _normalized_host() -> str:
    host = urlparse(settings.r2_endpoint_url).hostname or settings.r2_endpoint_url
    if host.startswith(settings.r2_bucket + "."):
        host = host[len(settings.r2_bucket) + 1 :]
    return host


def _configure(conn) -> None:
    # Keep DuckDB within Render's 512MB container limit.
    conn.execute("SET memory_limit = '350MB';")
    conn.execute("PRAGMA disable_object_cache;")
    conn.execute(f"SET threads = {settings.duckdb_threads};")
    temp_dir = _temp_directory().replace("'", "''")
    conn.execute(f"SET temp_directory = '{temp_dir}';")
    host = _normalized_host()
    conn.execute("LOAD httpfs;")
    conn.execute(f"SET s3_endpoint='{host}';")
    conn.execute("SET s3_region='us-east-1';")
    conn.execute(f"SET s3_access_key_id='{settings.r2_access_key_id}';")
    conn.execute(f"SET s3_secret_access_key='{settings.r2_secret_access_key}';")
    conn.execute("SET s3_url_style='path';")


def verify_httpfs() -> None:
    """Install + load httpfs at startup; fail loudly if unavailable."""
    conn = duckdb.connect()
    conn.execute("SET memory_limit = '350MB';")
    conn.execute("PRAGMA disable_object_cache;")
    conn.execute(f"SET threads = {settings.duckdb_threads};")
    try:
        conn.execute("INSTALL httpfs;")
    except Exception:
        # Extension may already be installed; LOAD will surface real errors.
        pass
    try:
        conn.execute("LOAD httpfs;")
    except Exception as exc:  # pragma: no cover - exercised by environment
        raise RuntimeError(f"Failed to load DuckDB httpfs extension: {exc}") from exc
    _configure(conn)
    conn.execute("SELECT 1").fetchone()
    conn.close()


def init_duckdb() -> None:
    verify_httpfs()


def open_connection():
    """Open a configured DuckDB connection for a batch of queries.

    Reusing one connection avoids re-installing ``httpfs`` and re-negotiating
    S3 for every rule in a pipeline run.
    """
    conn = duckdb.connect()
    conn.execute("SET memory_limit = '350MB';")
    conn.execute("PRAGMA disable_object_cache;")
    conn.execute(f"SET threads = {settings.duckdb_threads};")
    try:
        conn.execute("INSTALL httpfs;")
    except Exception:
        pass
    _configure(conn)
    return conn


def run_query_on(conn, sql: str):
    """Execute one DuckDB SQL statement inside a manual OTEL span."""
    with _TRACER.start_as_current_span(
        "duckdb.query",
        attributes={
            "db.system": "duckdb",
            "db.operation.name": sql.split(None, 1)[0].upper() if sql else "",
            "db.statement": sql[:2000],
        },
    ) as span:
        try:
            cur = conn.execute(sql)
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc)))
            raise
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall()
        span.set_attribute("duckdb.rows_returned", len(rows))
        return cols, rows


def query_dicts_on(conn, sql: str) -> list[dict]:
    cols, rows = run_query_on(conn, sql)
    return [dict(zip(cols, r, strict=False)) for r in rows]


def run_query(sql: str):
    conn = open_connection()
    try:
        return run_query_on(conn, sql)
    finally:
        conn.close()


def query_rows(sql: str) -> list[dict]:
    cols, rows = run_query(sql)
    return [dict(zip(cols, r, strict=False)) for r in rows]


def resolve_scenario_name(scenario: str) -> str:
    if str(scenario).startswith("generated_"):
        return "baseline_run"
    return scenario
