"""Tests for startup behavior (root AGENTS.md §4 step 1).

If RIOT_API_KEY is unset, the process exits with code 1 and an exact
message. run() wiring is verified with uvicorn stubbed out.
"""

from pathlib import Path

import pytest

from nexus import main
from nexus.config import Settings

EXPECTED_MESSAGE = (
    "RIOT_API_KEY is not set. Copy backend/.env.example to backend/.env and fill it in."
)


def _settings_with_key(key: str) -> Settings:
    settings = Settings()
    settings.riot_api_key = key
    return settings


def test_missing_key_exits_1_with_exact_message(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main.require_api_key(_settings_with_key(""))
    assert exc_info.value.code == 1
    assert capsys.readouterr().err == EXPECTED_MESSAGE + "\n"


def test_present_key_does_not_exit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main.require_api_key(_settings_with_key("placeholder"))
    assert capsys.readouterr().err == ""


def test_run_without_key_exits_before_serving(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        main.uvicorn, "run", lambda *args: pytest.fail("uvicorn must not start")
    )
    monkeypatch.delenv("RIOT_API_KEY", raising=False)
    monkeypatch.setattr(main, "load_settings", lambda: _settings_with_key(""))
    with pytest.raises(SystemExit) as exc_info:
        main.run()
    assert exc_info.value.code == 1
    assert EXPECTED_MESSAGE in capsys.readouterr().err


def test_run_rejects_unknown_storage_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(main.uvicorn, "run", lambda *args, **kwargs: None)
    monkeypatch.chdir(tmp_path)
    settings = _settings_with_key("placeholder")
    settings.storage_backend = "postgres"
    monkeypatch.setattr(main, "load_settings", lambda: settings)
    with pytest.raises(SystemExit) as exc_info:
        main.run()
    assert exc_info.value.code == 1
    assert "postgres" in capsys.readouterr().err
