"""Record live Riot responses to a replay dataset + derived test fixtures.

Dev tool for Nexus build-order step 4 (root AGENTS.md §12). Re-runnable:
point the MATCH_ID / GAME_ID constants at any live match and run again to
produce a new timestamped replay under ``replays/``.

Usage (from ``backend/``)::

    uv run python scripts/record_fixtures.py

Reads ``RIOT_API_KEY`` from the environment, falling back to ``backend/.env``.
Writes raw JSON verbatim -- no parsing, no cleanup, no prettifying of
content. Frames that carry no data (HTTP 204 "no data", or failed fetches
such as HTTP 400/403/500/timeouts) are stored as ``response: null``; the
per-frame outcome class (200 / 204 / error) is logged to stdout so the
operator can tell 204s apart from errors in the final report.

Each stored window keeps a single sub-frame (``response["frames"][:1]``):
a raw 10s window holds ~7 sub-frames per second of highly redundant data,
and keeping all of them balloons replays to tens of MB. The first
sub-frame represents game state at ``startingTime``; ``gameMetadata`` is
kept intact in every window so each frame stays self-contained.

Frame order in the replay file: newest-first (index 0 is "now", each
subsequent frame steps 10s further into the past).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from nexus.riot.client import RiotClient, aligned_starting_time

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger("record_fixtures")

MATCH_ID = "117030752644841637"
GAME_ID = "117030752644841640"
LEAGUE = "LCK"
HOME_CODE = "HLE"
AWAY_CODE = "T1"

REPLAY_FILENAME = "lck-2026-09-12-hle-vs-t1-g3.json"
MAX_FRAMES = 300
CONSECUTIVE_EMPTY_STOP = 3
SLEEP_BETWEEN_CALLS = 0.5
STEP_SECONDS = 10

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/
REPO_ROOT = BASE_DIR.parent
REPLAY_PATH = REPO_ROOT / "replays" / REPLAY_FILENAME
FIXTURES_DIR = BASE_DIR / "tests" / "fixtures"

_STAMP_FORMAT = "%Y-%m-%dT%H:%M:%S.000Z"


def load_api_key() -> str:
    key = os.environ.get("RIOT_API_KEY", "").strip()
    if key:
        return key
    env_path = BASE_DIR / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("RIOT_API_KEY="):
                return stripped.split("=", 1)[1].strip()
    sys.stderr.write(
        "RIOT_API_KEY is not set. Copy backend/.env.example to "
        "backend/.env and fill it in.\n"
    )
    raise SystemExit(1)


def thin_window_response(response: dict[str, Any] | None) -> dict[str, Any] | None:
    """Keep one sub-frame per window so replays stay small (see docstring)."""
    if response is None:
        return None
    inner = response.get("frames")
    if not isinstance(inner, list) or not inner:
        return response
    thinned = dict(response)
    thinned["frames"] = inner[:1]
    return thinned


def check_for_leaks(payload: str, api_key: str) -> list[str]:
    """Return descriptions of anything secret-looking in the payload."""
    findings: list[str] = []
    lowered = payload.lower()
    if api_key and api_key in payload:
        findings.append("payload contains the RIOT_API_KEY value")
    for marker in ("x-api-key", "set-cookie", "sessionid", "session_token"):
        if marker in lowered:
            findings.append(f"payload contains marker {marker!r}")
    return findings


async def main() -> None:
    api_key = load_api_key()
    client = RiotClient(api_key=api_key)
    try:
        live = await client.get_live()
        logger.info("getLive ok=%s has_data=%s", live.ok, live.data is not None)
        if live.data is not None:
            logger.info("getLive top-level keys: %s", sorted(live.data.keys()))

        event = await client.get_event_details(MATCH_ID)
        logger.info(
            "getEventDetails ok=%s has_data=%s", event.ok, event.data is not None
        )
        if event.data is None:
            logger.error("event_details fetch failed; aborting, nothing to save")
            raise SystemExit(1)
        logger.info("event_details top-level keys: %s", sorted(event.data.keys()))

        base = aligned_starting_time()
        base_dt = datetime.strptime(base, _STAMP_FORMAT).replace(tzinfo=UTC)
        logger.info("walking backward from %s in %ss steps", base, STEP_SECONDS)

        frames: list[dict[str, Any]] = []
        empty_run = 0
        counts = {"200": 0, "204": 0, "error": 0}
        first_response_keys: list[str] | None = None
        for k in range(MAX_FRAMES):
            stamp = (base_dt - timedelta(seconds=STEP_SECONDS * k)).strftime(
                _STAMP_FORMAT
            )
            result = await client.get_window(GAME_ID, stamp)
            frames.append(
                {"startingTime": stamp, "response": thin_window_response(result.data)}
            )
            if result.data is not None:
                empty_run = 0
                counts["200"] += 1
                outcome = "200"
                if first_response_keys is None:
                    first_response_keys = sorted(result.data.keys())
                    logger.info("window top-level keys: %s", first_response_keys)
            elif result.ok:
                empty_run += 1
                counts["204"] += 1
                outcome = "204"
            else:
                counts["error"] += 1
                outcome = "error"
            if k < 8 or k % 20 == 0 or outcome != "200":
                logger.info("frame %d %s -> %s", k, stamp, outcome)
            if empty_run >= CONSECUTIVE_EMPTY_STOP:
                logger.info(
                    "stopping after %d consecutive empty (204) frames", empty_run
                )
                break
            await asyncio.sleep(SLEEP_BETWEEN_CALLS)

        logger.info("collected %d frames: %s", len(frames), json.dumps(counts))

        end_check = await client.get_event_details(MATCH_ID)
        game_live_at_end: bool | None = None
        if end_check.data is not None:
            try:
                games = end_check.data["data"]["event"]["match"]["games"]
                state = next(
                    g.get("state") for g in games if str(g.get("id")) == GAME_ID
                )
                game_live_at_end = state == "inProgress"
            except (KeyError, TypeError, StopIteration):
                game_live_at_end = None
        logger.info("game still live at end of recording: %s", game_live_at_end)

        replay = {
            "match_id": MATCH_ID,
            "game_id": GAME_ID,
            "recorded_at": datetime.now(UTC).isoformat(),
            "league": LEAGUE,
            "teams": {"home": HOME_CODE, "away": AWAY_CODE},
            "event_details": event.data,
            "frames": frames,
        }
        serialized = json.dumps(replay, indent=2)
        leaks = check_for_leaks(serialized, api_key)
        if leaks:
            logger.error("scrub check failed: %s; NOT saving", "; ".join(leaks))
            raise SystemExit(1)
        logger.info("scrub check clean (no tokens/cookies/auth material)")
        REPLAY_PATH.write_text(serialized, encoding="utf-8")
        logger.info("wrote %s (%d bytes)", REPLAY_PATH, len(serialized))

        # --- Derived fixtures (same recording, smaller slices) ---
        FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
        (FIXTURES_DIR / "event_details.json").write_text(
            json.dumps(event.data, indent=2), encoding="utf-8"
        )
        mid = len(frames) // 2
        sequence = frames[max(0, mid - 15) : mid + 15]
        (FIXTURES_DIR / "window_sequence.json").write_text(
            json.dumps(sequence, indent=2), encoding="utf-8"
        )
        single: dict[str, Any] | None = None
        for entry in frames[mid:] + frames[mid - 1 :: -1]:
            if entry["response"] is not None:
                single = entry["response"]
                break
        if single is None:
            logger.error("no non-null frame found; cannot write window_single")
            raise SystemExit(1)
        (FIXTURES_DIR / "window_single.json").write_text(
            json.dumps(single, indent=2), encoding="utf-8"
        )
        if live.data is not None:
            (FIXTURES_DIR / "get_live.json").write_text(
                json.dumps(live.data, indent=2), encoding="utf-8"
            )
        else:
            logger.warning("getLive had no data; get_live.json not written")
        logger.info("fixtures written to %s", FIXTURES_DIR)
        logger.info(
            "sequence covers %s .. %s",
            sequence[0]["startingTime"],
            sequence[-1]["startingTime"],
        )
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
