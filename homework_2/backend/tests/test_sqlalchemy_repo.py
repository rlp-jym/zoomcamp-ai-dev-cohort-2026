"""Tests specific to the SQLAlchemy preferences repository.

Uses in-memory SQLite only — never the file on disk, never Postgres.
Shared get/set/all behavior lives in the parametrized suite in
test_storage.py; only adapter-specific behavior is tested here.
"""

from pathlib import Path

from sqlalchemy import create_engine, inspect

from nexus.storage.sqlalchemy_repo import (
    Base,
    SqlAlchemyPreferencesRepository,
    ensure_sqlite_directory,
)


def _repo() -> SqlAlchemyPreferencesRepository:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return SqlAlchemyPreferencesRepository(engine)


def test_create_all_creates_the_preferences_table() -> None:
    engine = create_engine("sqlite:///:memory:")
    assert inspect(engine).get_table_names() == []
    Base.metadata.create_all(engine)
    assert inspect(engine).get_table_names() == ["preferences"]


def test_set_twice_on_same_key_upserts_without_raising() -> None:
    repo = _repo()
    repo.set("view_mode", "standard")
    repo.set("view_mode", "deep")
    assert repo.get("view_mode") == "deep"
    assert repo.all() == {"view_mode": "deep"}


def test_all_returns_every_row_not_a_fixed_set() -> None:
    repo = _repo()
    repo.set("custom-key", "custom-value")
    assert repo.all() == {"custom-key": "custom-value"}


def test_values_survive_new_instance_on_shared_engine() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SqlAlchemyPreferencesRepository(engine).set("pinned_match_id", "abc")
    fresh = SqlAlchemyPreferencesRepository(engine)
    assert fresh.get("pinned_match_id") == "abc"


def test_ensure_sqlite_directory_creates_missing_parents(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "dir" / "nexus.db"
    ensure_sqlite_directory(f"sqlite:///{target}")
    assert target.parent.is_dir()


def test_ensure_sqlite_directory_ignores_memory_and_non_sqlite() -> None:
    ensure_sqlite_directory("sqlite:///:memory:")
    ensure_sqlite_directory("postgresql://user@host/db")
