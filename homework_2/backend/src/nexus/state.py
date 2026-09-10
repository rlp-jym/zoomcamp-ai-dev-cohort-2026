"""In-memory scoreboard state with atomic swap.

The poller replaces the whole object; readers always see one complete
snapshot. A failed poll simply never swaps, so last known values stay.
"""

import threading
from datetime import datetime, timezone
from typing import Any


def idle_state(now: datetime | None = None) -> dict[str, Any]:
    """Build a contract-shaped idle state (no live match)."""
    moment = now or datetime.now(timezone.utc)  # noqa: UP017 - spelling matches root AGENTS.md §6 verbatim
    return {
        "status": "idle",
        "stale": False,
        "lastUpdated": moment.isoformat(),
        "match": None,
        "game": None,
    }


class AppState:
    """Thread-safe holder for the current state object."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: dict[str, Any] = idle_state()

    def get(self) -> dict[str, Any]:
        with self._lock:
            return self._state

    def swap(self, next_state: dict[str, Any]) -> None:
        with self._lock:
            self._state = next_state
