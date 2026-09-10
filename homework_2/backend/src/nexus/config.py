"""Environment settings (root AGENTS.md §10).

Values come from the process environment with backend/.env as a fallback.
Never hardcode these anywhere else.
"""

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """All Nexus configuration knobs."""

    model_config = SettingsConfigDict(
        env_file=str(_BACKEND_DIR / ".env"), extra="ignore"
    )

    riot_api_key: str = ""
    nexus_port: int = 8000
    storage_backend: Literal["json", "postgres"] = "json"
    poll_live_seconds: int = 10
    poll_between_seconds: int = 30
    poll_idle_seconds: int = 60
    poll_max_backoff_seconds: int = 300


def load_settings() -> Settings:
    return Settings()


def preferences_path() -> Path:
    """Filesystem location of the JSON preferences file."""
    return _BACKEND_DIR / ".nexus" / "preferences.json"
