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
        self.duckdb_threads = int(os.getenv("DUCKDB_THREADS", "2"))
        self.app_env = os.getenv("APP_ENV", "dev")
        # Materiality / tolerance for billings-vs-GL reconciliation.
        # config uses a percentage (0.5 == 0.5%); we store it as a fraction.
        self.recon_tolerance_pct = float(os.getenv("RECON_TOLERANCE_PCT", "0.5")) / 100.0

        # Safety valve: cap per-exception agent messages per pipeline run.
        self.max_agent_messages_per_run = int(
            os.getenv("MAX_AGENT_MESSAGES_PER_RUN", "3")
        )

        # OTEL (SPEC §13): Postgres exporter is always on; intervals only
        # tune the batch cadence. No external telemetry endpoint required.
        self.otel_service_name = os.getenv("OTEL_SERVICE_NAME", "rlp-platform")
        self.otel_metric_interval_seconds = int(
            os.getenv("OTEL_METRIC_INTERVAL_SECONDS", "60")
        )
        self.otel_retention_days = int(os.getenv("OTEL_RETENTION_DAYS", "30"))

        # Scheduler (SPEC §6) + Controller verification (SPEC §18).
        self.controller_interval_minutes = int(
            os.getenv("CONTROLLER_INTERVAL_MINUTES", "15")
        )
        self.controller_stale_hours = float(os.getenv("CONTROLLER_STALE_HOURS", "24"))

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
