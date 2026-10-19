"""DuckDB connection with httpfs for reading Parquet from S3."""

from urllib.parse import urlparse

import duckdb

from backend.config import settings


def _normalized_host() -> str:
    host = urlparse(settings.r2_endpoint_url).hostname or settings.r2_endpoint_url
    if host.startswith(settings.r2_bucket + "."):
        host = host[len(settings.r2_bucket) + 1 :]
    return host


def _configure(conn) -> None:
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


def run_query(sql: str):
    conn = duckdb.connect()
    try:
        conn.execute("INSTALL httpfs;")
    except Exception:
        pass
    _configure(conn)
    cur = conn.execute(sql)
    cols = [d[0] for d in cur.description] if cur.description else []
    rows = cur.fetchall()
    conn.close()
    return cols, rows


def query_rows(sql: str) -> list[dict]:
    cols, rows = run_query(sql)
    return [dict(zip(cols, r)) for r in rows]
