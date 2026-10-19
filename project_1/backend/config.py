"""Application configuration loaded from environment variables."""

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = PROJECT_ROOT / "frontend"
TEMPLATES_DIR = FRONTEND_DIR / "templates"
STATIC_DIR = FRONTEND_DIR / "static"

load_dotenv(PROJECT_ROOT / ".env", override=False)


class Settings:
    def __init__(self):
        self.database_url = os.getenv("DATABASE_URL")
        self.r2_endpoint_url = os.getenv("R2_ENDPOINT_URL")
        self.r2_access_key_id = os.getenv("R2_ACCESS_KEY_ID")
        self.r2_secret_access_key = os.getenv("R2_SECRET_ACCESS_KEY")
        self.r2_bucket = os.getenv("R2_BUCKET")

        self.groq_api_key = os.getenv("GROQ_API_KEY") or None
        self.gh_token = os.getenv("GH_TOKEN") or None
        self.webhook_token = os.getenv("WEBHOOK_TOKEN", "dev-webhook-token")
        self.persona_cookie = os.getenv("PERSONA_COOKIE_NAME", "persona")
        self.app_env = os.getenv("APP_ENV", "dev")

        missing = []
        for name, value in (
            ("DATABASE_URL", self.database_url),
            ("R2_ENDPOINT_URL", self.r2_endpoint_url),
            ("R2_ACCESS_KEY_ID", self.r2_access_key_id),
            ("R2_SECRET_ACCESS_KEY", self.r2_secret_access_key),
            ("R2_BUCKET", self.r2_bucket),
        ):
            if not value:
                missing.append(name)
        if missing:
            raise RuntimeError(
                "Missing required environment variables: " + ", ".join(missing)
            )


settings = Settings()
