"""Tests for settings loading (root AGENTS.md §10)."""

import os
from pathlib import Path

import pytest
from pydantic_settings import SettingsConfigDict

from nexus.config import Settings


def _isolated_settings_class(env_file: Path) -> type[Settings]:
    class IsolatedSettings(Settings):
        model_config = SettingsConfigDict(env_file=str(env_file))

    return IsolatedSettings


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "RIOT_API_KEY",
        "NEXUS_PORT",
        "STORAGE_BACKEND",
        "DATABASE_URL",
        "POLL_LIVE_SECONDS",
        "POLL_BETWEEN_SECONDS",
        "POLL_IDLE_SECONDS",
        "POLL_MAX_BACKOFF_SECONDS",
    ):
        monkeypatch.delenv(key, raising=False)


def test_defaults_with_empty_env_file(tmp_path: Path, clean_env: None) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("# empty\n", encoding="utf-8")
    settings = _isolated_settings_class(env_file)()
    assert settings.riot_api_key == ""
    assert settings.nexus_port == 8000
    assert settings.storage_backend == "sqlalchemy"
    assert settings.database_url == "sqlite:///.nexus/nexus.db"
    assert settings.poll_live_seconds == 10
    assert settings.poll_between_seconds == 30
    assert settings.poll_idle_seconds == 60
    assert settings.poll_max_backoff_seconds == 300


def test_env_file_values_are_read(tmp_path: Path, clean_env: None) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "RIOT_API_KEY=from-file\nNEXUS_PORT=9001\nPOLL_LIVE_SECONDS=5\n",
        encoding="utf-8",
    )
    settings = _isolated_settings_class(env_file)()
    assert settings.riot_api_key == "from-file"
    assert settings.nexus_port == 9001
    assert settings.poll_live_seconds == 5


def test_process_env_beats_env_file(
    tmp_path: Path,
    clean_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("NEXUS_PORT=9001\n", encoding="utf-8")
    monkeypatch.setenv("NEXUS_PORT", "9002")
    settings = _isolated_settings_class(env_file)()
    assert settings.nexus_port == 9002
    assert os.environ["NEXUS_PORT"] == "9002"
