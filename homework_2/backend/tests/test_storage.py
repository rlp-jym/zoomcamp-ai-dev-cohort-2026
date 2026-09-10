"""Tests for both preferences repository adapters.

The shared suite is parametrized over the JSON and SQLAlchemy
implementations: identical behavior is proven, not asserted. Backend-specific
tolerances (missing/corrupt files) stay in per-adapter tests.
"""

import logging
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from nexus import main
from nexus.config import Settings
from nexus.storage.base import PreferencesRepository
from nexus.storage.json_file import JsonFilePreferencesRepository
from nexus.storage.sqlalchemy_repo import (
    Base,
    SqlAlchemyPreferencesRepository,
)


@pytest.fixture(params=["json", "sqlalchemy"])
def repo(request: pytest.FixtureRequest, tmp_path: Path) -> PreferencesRepository:
    if request.param == "json":
        return JsonFilePreferencesRepository(tmp_path / "prefs.json")
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return SqlAlchemyPreferencesRepository(engine)


def test_round_trip_get_set_all(repo: PreferencesRepository) -> None:
    assert repo.get("pinned_match_id") is None
    assert repo.all() == {}
    repo.set("pinned_match_id", "match-123")
    repo.set("view_mode", "deep")
    assert repo.get("pinned_match_id") == "match-123"
    assert repo.get("view_mode") == "deep"
    assert repo.all() == {"pinned_match_id": "match-123", "view_mode": "deep"}


def test_overwrite_existing_key_upserts(repo: PreferencesRepository) -> None:
    repo.set("view_mode", "standard")
    repo.set("view_mode", "deep")
    assert repo.get("view_mode") == "deep"
    assert repo.all() == {"view_mode": "deep"}


def test_missing_key_returns_none(repo: PreferencesRepository) -> None:
    assert repo.get("no-such-key") is None


def test_empty_store_reads_as_empty(repo: PreferencesRepository) -> None:
    assert repo.all() == {}


def test_creates_parent_directory(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "dir" / "prefs.json"
    repo = JsonFilePreferencesRepository(target)
    repo.set("view_mode", "standard")
    assert target.exists()


def test_missing_file_reads_as_empty(tmp_path: Path) -> None:
    repo = JsonFilePreferencesRepository(tmp_path / "does-not-exist.json")
    assert repo.get("anything") is None
    assert repo.all() == {}


def test_corrupt_file_reads_as_empty_without_raising(tmp_path: Path) -> None:
    target = tmp_path / "prefs.json"
    target.write_text("{not valid json", encoding="utf-8")
    repo = JsonFilePreferencesRepository(target)
    assert repo.get("view_mode") is None
    assert repo.all() == {}


def test_set_after_corrupt_file_recovers(tmp_path: Path) -> None:
    target = tmp_path / "prefs.json"
    target.write_text("garbage", encoding="utf-8")
    repo = JsonFilePreferencesRepository(target)
    repo.set("view_mode", "deep")
    assert repo.get("view_mode") == "deep"


def test_json_values_survive_new_instance(tmp_path: Path) -> None:
    target = tmp_path / "prefs.json"
    JsonFilePreferencesRepository(target).set("pinned_match_id", "abc")
    fresh = JsonFilePreferencesRepository(target)
    assert fresh.get("pinned_match_id") == "abc"


def test_create_repository_selects_json(tmp_path: Path) -> None:
    settings = Settings(storage_backend="json")
    repo = main.create_repository(settings)
    assert isinstance(repo, JsonFilePreferencesRepository)
    repo.set("view_mode", "deep")
    assert repo.get("view_mode") == "deep"


def test_create_repository_selects_sqlalchemy(tmp_path: Path) -> None:
    db_file = tmp_path / "sub" / "test.db"
    settings = Settings(
        storage_backend="sqlalchemy", database_url=f"sqlite:///{db_file}"
    )
    repo = main.create_repository(settings)
    assert isinstance(repo, SqlAlchemyPreferencesRepository)
    assert db_file.exists()
    repo.set("view_mode", "deep")
    assert repo.get("view_mode") == "deep"


def test_create_repository_logs_resolved_db_path(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    db_file = tmp_path / "test.db"
    settings = Settings(
        storage_backend="sqlalchemy", database_url=f"sqlite:///{db_file}"
    )
    with caplog.at_level(logging.INFO, logger="nexus.main"):
        main.create_repository(settings)
    assert str(db_file) in caplog.text


def test_create_repository_rejects_unknown_backend() -> None:
    settings = Settings(storage_backend="json")
    settings.storage_backend = "postgres"
    with pytest.raises(ValueError, match="postgres"):
        main.create_repository(settings)
