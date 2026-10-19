"""Application configuration loaded from environment variables."""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = PROJECT_ROOT / "frontend"
TEMPLATES_DIR = FRONTEND_DIR / "templates"
STATIC_DIR = FRONTEND_DIR / "static"


class Settings:
    app_env: str = os.getenv("APP_ENV", "dev")
    persona_cookie: str = os.getenv("PERSONA_COOKIE_NAME", "persona")


settings = Settings()