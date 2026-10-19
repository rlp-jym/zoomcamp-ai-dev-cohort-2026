"""Postgres connection pool and raw SQL helpers (psycopg3)."""

import os
from pathlib import Path

from psycopg_pool import ConnectionPool

from backend.config import PROJECT_ROOT, settings

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

_pool: ConnectionPool | None = None


def init_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=settings.database_url,
            min_size=1,
            max_size=5,
            open=True,
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


def execute(sql: str, params=None, fetch: bool = False):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            if fetch:
                cols = [d.name for d in (cur.description or [])]
                rows = cur.fetchall()
                return cols, [dict(zip(cols, r)) for r in rows]
            conn.commit()
            return None


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
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in (cur.description or [])]
            return dict(zip(cols, row))


def fetch_all(sql: str, params=None):
    _cols, rows = execute(sql, params, fetch=True)
    return rows


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
