"""Adaptive poller loop (root AGENTS.md §4 tick, §6 intervals).

Live mode walks the §4 tick sequence verbatim: getLive for match
detection (or the pinned match), getEventDetails into normalize, the
livestats window into normalize, build_state, atomic swap. Window calls
use window_starting_time(), offset clear of the anti-spoiler buffer.

REPLAY MODE (dev/demo only, not part of the product contract): with
POLL_SOURCE=replay, the poller makes no Riot calls. main.run() loads the
replay JSON once at startup and hands the parsed dict in; the poller walks
its frames oldest-first at one frame per REPLAY_INTERVAL_SECONDS through
the same normalize_window -> build_state pipeline, then loops. Replay mode
is unreachable when POLL_SOURCE=live (the default).

Success/error accounting comes from FetchResult.ok: HTTP 204 is
ok-without-data and resets the backoff; a failed fetch keeps every known
value, flips only the stale flag, and backs off. lastUpdated tracks the
last successful update, so a stuck board shows an honestly aging
timestamp rather than a fresh one over stale data.
"""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from pydantic import ValidationError

from nexus.config import Settings
from nexus.riot import models
from nexus.riot.client import FetchResult, window_starting_time
from nexus.riot.normalize import (
    GameContext,
    MatchState,
    build_state,
    normalize_event_details,
    normalize_window,
)
from nexus.state import AppState, idle_state

logger = logging.getLogger(__name__)

# Replay cadence: one recorded frame per tick, slow enough to follow.
REPLAY_INTERVAL_SECONDS = 2.0


class PollerClient(Protocol):
    """Structural type for the Riot client; tests inject a fake."""

    async def get_live(self) -> FetchResult: ...
    async def get_event_details(self, match_id: str) -> FetchResult: ...
    async def get_window(self, game_id: str, starting_time: str) -> FetchResult: ...


def _live_match_id(data: Any) -> str | None:
    """First event id with state inProgress, or None when nothing is live."""
    if not isinstance(data, dict):
        return None
    try:
        live = models.GetLive.model_validate(data)
    except ValidationError:
        return None
    schedule = live.data.schedule if live.data is not None else None
    events = schedule.events if schedule is not None else None
    for event in events or []:
        if event.state == "inProgress" and isinstance(event.id, str) and event.id:
            return event.id
    return None


def _live_game_id(data: Any, game_number: int) -> str | None:
    """Game id of the in-progress game with this number, or None."""
    if not isinstance(data, dict):
        return None
    try:
        details = models.EventDetails.model_validate(data)
    except ValidationError:
        return None
    event = details.data.event if details.data is not None else None
    match = event.match if event is not None else None
    games = match.games if match is not None else None
    for game in games or []:
        if (
            game.state == "inProgress"
            and game.number == game_number
            and isinstance(game.id, str)
            and game.id
        ):
            return game.id
    return None


class Poller:
    """One poller tick per call; run() loops forever."""

    def __init__(
        self,
        client: PollerClient | None,
        store: AppState,
        settings: Settings,
        get_pinned: Callable[[], str | None] | None = None,
        replay: dict[str, Any] | None = None,
    ) -> None:
        self.client = client
        self.store = store
        self.settings = settings
        self._get_pinned = get_pinned
        self._consecutive_errors = 0
        self._game_key: tuple[str, int] | None = None
        self._context = GameContext()
        self._replay_match: MatchState | None = None
        self._replay_frames: list[dict[str, Any]] = []
        self._replay_index = 0
        if settings.poll_source == "replay":
            if replay is None:
                raise ValueError("POLL_SOURCE=replay requires replay data")
            self._load_replay(replay)
        elif client is None:
            raise ValueError("live mode requires a Riot client")

    def _load_replay(self, replay: dict[str, Any]) -> None:
        match = normalize_event_details(replay.get("event_details", {}))
        if match is None or match.game_number is None:
            raise ValueError("replay event_details has no live game")
        entries = replay.get("frames", [])
        frames = [
            entry["response"]
            for entry in reversed(entries)
            if isinstance(entry, dict) and entry.get("response") is not None
        ]
        if not frames:
            raise ValueError("replay file contains no usable frames")
        self._replay_match = match
        self._replay_frames = frames
        self._replay_index = 0
        self._context = GameContext()
        logger.info("Replay mode: %d frames for match %s", len(frames), match.match_id)

    def _backoff_interval(self) -> float:
        # Retry base reuses the fastest cadence (the live interval), then
        # doubles per consecutive error, capped at the configured maximum.
        base = self.settings.poll_live_seconds
        interval = base * (2 ** (self._consecutive_errors - 1))
        return float(min(interval, self.settings.poll_max_backoff_seconds))

    async def tick(self) -> float:
        """Run one poll. Returns seconds the loop should sleep next."""
        if self.settings.poll_source == "replay":
            return await self._replay_tick()
        try:
            return await self._live_tick()
        except Exception as exc:  # noqa: BLE001 - the loop must never exit on error
            logger.warning("Poller tick failed: %s", exc)
            return self._fail()

    async def _live_tick(self) -> float:
        assert self.client is not None
        now = datetime.now(UTC)
        match_id: str | None = None
        if self._get_pinned is not None:
            match_id = self._get_pinned()
        if match_id is None:
            result = await self.client.get_live()
            if not result.ok:
                return self._fail()
            match_id = _live_match_id(result.data)
            if match_id is None:
                self._succeed(idle_state(now))
                return float(self.settings.poll_idle_seconds)
        event = await self.client.get_event_details(match_id)
        if not event.ok:
            return self._fail()
        if event.data is None:
            # Success with nothing to report: keep values, clear stale.
            return self._keep(float(self.settings.poll_between_seconds))
        match = normalize_event_details(event.data)
        if match is None:
            self._succeed(idle_state(now))
            return float(self.settings.poll_idle_seconds)
        if match.game_number is None:
            self._succeed(build_state(match, None, False, now))
            return float(self.settings.poll_between_seconds)
        game_id = _live_game_id(event.data, match.game_number)
        if game_id is None:
            return self._fail()
        game_key = (match.match_id, match.game_number)
        if self._game_key != game_key:
            self._game_key = game_key
            self._context = GameContext()
        window = await self.client.get_window(game_id, window_starting_time())
        if not window.ok:
            return self._fail()
        if window.data is None:
            # 204 feed gap while the game is live: keep values, clear stale.
            return self._keep(float(self.settings.poll_live_seconds))
        game = normalize_window(window.data, match, self._context)
        if game is None:
            return self._fail()
        self._succeed(build_state(match, game, False, now))
        return float(self.settings.poll_live_seconds)

    async def _replay_tick(self) -> float:
        try:
            assert self._replay_match is not None
            frame = self._replay_frames[self._replay_index]
            game = normalize_window(frame, self._replay_match, self._context)
            self._replay_index += 1
            if self._replay_index >= len(self._replay_frames):
                self._replay_index = 0
                self._context = GameContext()
            if game is None:
                return REPLAY_INTERVAL_SECONDS
            self._consecutive_errors = 0
            self.store.swap(
                build_state(self._replay_match, game, False, datetime.now(UTC))
            )
        except Exception as exc:  # noqa: BLE001 - demo loop must never exit
            logger.warning("Replay tick failed: %s", exc)
        return REPLAY_INTERVAL_SECONDS

    def _succeed(self, state: dict[str, Any]) -> None:
        """Successful poll with fresh data: reset backoff, swap state."""
        self._consecutive_errors = 0
        self.store.swap(state)

    def _keep(self, interval: float) -> float:
        """Successful poll with no new data: keep values, clear stale."""
        self._consecutive_errors = 0
        current = self.store.get()
        if current["stale"]:
            self.store.swap({**current, "stale": False})
        return interval

    def _fail(self) -> float:
        """Shared error path: keep values, flag stale, back off."""
        self._consecutive_errors += 1
        self._mark_stale()
        return self._backoff_interval()

    def _mark_stale(self) -> None:
        """Flip only the stale flag; every known value stays on screen."""
        current = self.store.get()
        if not current["stale"]:
            self.store.swap({**current, "stale": True})

    async def run(self) -> None:
        """Loop forever. Never exits on error; cancel the task to stop."""
        while True:
            interval = await self.tick()
            await asyncio.sleep(interval)
