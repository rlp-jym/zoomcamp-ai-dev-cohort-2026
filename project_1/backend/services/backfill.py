"""Trigger GitHub Action backfill when scenarios table is empty."""

import logging
import os

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)


def trigger_backfill() -> None:
    if not settings.gh_token:
        logger.warning("GH_TOKEN not set; skipping backfill trigger")
        return

    repo = os.getenv("GITHUB_REPOSITORY", "rlp-jym/zoomcamp-ai-dev-cohort-2026")
    workflow = os.getenv("BACKFILL_WORKFLOW", "scenario-generate.yml")
    ref = os.getenv("GITHUB_REF_NAME", "main")
    url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow}/dispatches"
    headers = {
        "Authorization": f"Bearer {settings.gh_token}",
        "Accept": "application/vnd.github+json",
    }
    payload = {
        "ref": ref,
        "inputs": {"scenario_name": "baseline_run", "seed": "9"},
    }
    try:
        resp = httpx.post(url, headers=headers, json=payload, timeout=10.0)
        resp.raise_for_status()
        logger.info("Backfill triggered for baseline_run")
    except Exception as exc:  # pragma: no cover - network dependent
        logger.error("Failed to trigger backfill: %s", exc)
