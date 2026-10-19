"""Postgres connection pool and raw SQL helpers (psycopg3)."""

import logging
import time
from pathlib import Path

from psycopg import OperationalError
from psycopg_pool import ConnectionPool

from backend.config import settings

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

_pool: ConnectionPool | None = None
_log = logging.getLogger(__name__)


def init_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=settings.database_url,
            min_size=1,
            max_size=5,
            open=True,
            # Managed Postgres (Neon) silently drops idle TLS connections;
            # keepalives surface dead peers and `check` avoids handing one out.
            kwargs={
                "keepalives": 1,
                "keepalives_idle": 30,
                "keepalives_interval": 10,
                "keepalives_count": 3,
            },
            check=ConnectionPool.check_connection,
        )
    return _pool


def get_pool() -> ConnectionPool:
    if _pool is None:
        init_pool()
    return _pool


def get_connection():
    return get_pool().connection()


def apply_schema() -> None:
    sql = SCHEMA_PATH.read_text(encoding="utf-8")
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()


def _with_retry(op, retries: int = 1, delay: float = 0.5):
    """Run one DB operation, retrying once on a dropped-connection error.

    Managed Postgres providers (Neon free tier) close idle connections; a
    single retry on a fresh pooled connection keeps background jobs and
    long pipeline requests resilient.
    """
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            return op()
        except OperationalError as exc:
            last_exc = exc
            if attempt >= retries:
                raise
            _log.warning("DB connection error (attempt %s), retrying: %s", attempt + 1, exc)
            time.sleep(delay)
    raise last_exc  # pragma: no cover - unreachable


def execute(sql: str, params=None, fetch: bool = False):
    def _run():
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params or ())
                if fetch:
                    cols = [d.name for d in (cur.description or [])]
                    rows = cur.fetchall()
                    return cols, [dict(zip(cols, r, strict=False)) for r in rows]
                conn.commit()
                return None

    return _with_retry(_run)


def execute_many(sql: str, params_list: list[tuple]) -> int:
    if not params_list:
        return 0
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, params_list)
            count = cur.rowcount
        conn.commit()
    return count if count is not None and count >= 0 else len(params_list)

def fetch_one(sql: str, params=None):
    def _run():
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params or ())
                row = cur.fetchone()
                if row is None:
                    return None
                cols = [d.name for d in (cur.description or [])]
                return dict(zip(cols, row, strict=False))

    return _with_retry(_run)


def fetch_all(sql: str, params=None):
    _cols, rows = execute(sql, params, fetch=True)
    return rows


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
