"""Adaptive poller loop (root AGENTS.md §4 tick, §6 intervals).

Until build-order step 4 (recorded fixtures) exists, a successful tick sets
state to idle and returns — no parsing is attempted.

Success/error accounting comes from FetchResult.ok: HTTP 204 is
ok-without-data and resets the backoff; a failed fetch keeps every known
value, flips only the stale flag, and backs off. lastUpdated tracks the
last successful update, so a stuck board shows an honestly aging
timestamp rather than a fresh one over stale data.
"""

import asyncio
import logging
from typing import Protocol

from nexus.config import Settings
from nexus.riot.client import FetchResult
from nexus.state import AppState, idle_state
from nexus.storage.base import PreferencesRepository

logger = logging.getLogger(__name__)


class PollerClient(Protocol):
    """Structural type for the Riot client; tests inject a fake."""

    async def get_live(self) -> FetchResult: ...
    async def get_event_details(self, match_id: str) -> FetchResult: ...
    async def get_window(self, game_id: str, starting_time: str) -> FetchResult: ...


class Poller:
    """One poller tick per call; run() loops forever."""

    def __init__(
        self,
        client: PollerClient,
        store: AppState,
        repo: PreferencesRepository,
        settings: Settings,
    ) -> None:
        self.client = client
        self.store = store
        # Reserved for the step-6 pin override (root §4 tick step 1).
        self.repo = repo
        self.settings = settings
        self._consecutive_errors = 0

    def _backoff_interval(self) -> float:
        # Retry base reuses the fastest cadence (the live interval), then
        # doubles per consecutive error, capped at the configured maximum.
        base = self.settings.poll_live_seconds
        interval = base * (2 ** (self._consecutive_errors - 1))
        return float(min(interval, self.settings.poll_max_backoff_seconds))

    async def tick(self) -> float:
        """Run one poll. Returns seconds the loop should sleep next."""
        try:
            result = await self.client.get_live()
        except Exception as exc:  # noqa: BLE001 - the loop must never exit on error
            logger.warning("Poller tick failed: %s", exc)
            return self._fail()
        if not result.ok:
            return self._fail()
        _ = result.data
        self._consecutive_errors = 0
        self.store.swap(idle_state())
        return float(self.settings.poll_idle_seconds)

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
