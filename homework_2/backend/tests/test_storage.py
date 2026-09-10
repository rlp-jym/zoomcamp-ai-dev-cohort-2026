"""Tests for the JSON-file preferences repository.

Covers root AGENTS.md §11 and §14: round-trip get/set/all, missing file,
and corrupt file tolerance.
"""

from pathlib import Path

from nexus.storage.json_file import JsonFilePreferencesRepository


def test_round_trip_get_set_all(tmp_path: Path) -> None:
    repo = JsonFilePreferencesRepository(tmp_path / "prefs.json")
    assert repo.get("pinned_match_id") is None
    assert repo.all() == {}
    repo.set("pinned_match_id", "match-123")
    repo.set("view_mode", "deep")
    assert repo.get("pinned_match_id") == "match-123"
    assert repo.get("view_mode") == "deep"
    assert repo.all() == {"pinned_match_id": "match-123", "view_mode": "deep"}


def test_overwrite_existing_key(tmp_path: Path) -> None:
    repo = JsonFilePreferencesRepository(tmp_path / "prefs.json")
    repo.set("view_mode", "standard")
    repo.set("view_mode", "deep")
    assert repo.get("view_mode") == "deep"
    assert repo.all() == {"view_mode": "deep"}


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


def test_values_survive_new_instance(tmp_path: Path) -> None:
    target = tmp_path / "prefs.json"
    JsonFilePreferencesRepository(target).set("pinned_match_id", "abc")
    fresh = JsonFilePreferencesRepository(target)
    assert fresh.get("pinned_match_id") == "abc"
