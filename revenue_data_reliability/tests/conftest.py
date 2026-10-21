"""Test setup: ensure the Postgres schema exists before tests run."""

from backend.db import apply_schema, init_pool, seed
from backend.db.fixture import ensure_baseline_fixture


def pytest_sessionstart(session):
    init_pool()
    apply_schema()
    seed()
    ensure_baseline_fixture()