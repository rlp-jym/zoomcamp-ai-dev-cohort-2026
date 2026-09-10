"""Tests for the poller loop (root AGENTS.md §4 tick, §6 intervals).

The poller takes a fake client: no HTTP here. Until build-order step 4
(recorded fixtures) exists, a successful tick sets state to idle. A failed
fetch never clears values but flips the stale flag (specs §8.3, FR-18).
"""

import asyncio
from pathlib import Path
from typing import Any

import pytest

from nexus import main
from nexus.config import Settings
from nexus.poller import Poller
from nexus.riot.client import FetchResult
from nexus.state import AppState, idle_state


def ok(data: Any) -> FetchResult:
    return FetchResult(data=data, ok=True)


def no_data() -> FetchResult:
    """HTTP 204: success with nothing to report."""
    return FetchResult(data=None, ok=True)


def failed() -> FetchResult:
    """A fetch that failed (403, 500, timeout, bad JSON)."""
    return FetchResult(data=None, ok=False)


class FakeClient:
    """Canned get_live script of FetchResults; Exceptions raise."""

    def __init__(self, script: list[Any]) -> None:
        self._script = list(script)
        self.calls = 0

    async def get_live(self) -> FetchResult:
        self.calls += 1
        if not self._script:
            return ok({})
        action = self._script.pop(0)
        if isinstance(action, Exception):
            raise action
        return action

    async def get_event_details(self, match_id: str) -> FetchResult:
        return ok({})

    async def get_window(self, game_id: str, starting_time: str) -> FetchResult:
        return ok({})


def _settings(**overrides: Any) -> Settings:
    return Settings(**overrides)


def _poller(tmp_path: Path, script: list[Any], **overrides: Any) -> Poller:
    return Poller(
        client=FakeClient(script),
        store=AppState(),
        settings=_settings(**overrides),
    )


async def test_tick_sets_idle_on_empty_success(tmp_path: Path) -> None:
    poller = _poller(tmp_path, [ok({})])
    stale_before = idle_state()
    stale_before["stale"] = True
    poller.store.swap(stale_before)
    interval = await poller.tick()
    assert interval == 60
    current = poller.store.get()
    assert current["status"] == "idle"
    assert current["stale"] is False


async def test_tick_treats_204_as_success(tmp_path: Path) -> None:
    poller = _poller(tmp_path, [RuntimeError("boom"), no_data()])
    assert await poller.tick() == 10
    # A 204 counts as success: backoff resets to the normal cadence.
    assert await poller.tick() == 60
    current = poller.store.get()
    assert current["status"] == "idle"
    assert current["stale"] is False


async def test_failed_fetch_sets_stale_and_keeps_values(
    tmp_path: Path,
) -> None:
    poller = _poller(tmp_path, [failed()])
    before = poller.store.get()
    assert before["stale"] is False
    assert await poller.tick() == 10
    after = poller.store.get()
    assert after["stale"] is True
    assert after["status"] == before["status"]
    assert after["match"] is None
    assert after["game"] is None
    # lastUpdated tracks the last successful update, not the failed attempt.
    assert after["lastUpdated"] == before["lastUpdated"]


async def test_unexpected_raise_also_sets_stale(tmp_path: Path) -> None:
    poller = _poller(tmp_path, [RuntimeError("boom")])
    assert await poller.tick() == 10
    assert poller.store.get()["stale"] is True


async def test_stale_clears_on_next_success(tmp_path: Path) -> None:
    poller = _poller(tmp_path, [failed(), ok({})])
    assert await poller.tick() == 10
    assert poller.store.get()["stale"] is True
    assert await poller.tick() == 60
    current = poller.store.get()
    assert current["stale"] is False
    assert current["status"] == "idle"


async def test_consecutive_failures_keep_stale_without_clearing(
    tmp_path: Path,
) -> None:
    poller = _poller(tmp_path, [failed(), RuntimeError("x")])
    await poller.tick()
    first = poller.store.get()
    await poller.tick()
    second = poller.store.get()
    assert first["stale"] is True
    assert second["stale"] is True
    assert second["match"] is None
    assert second["game"] is None


async def test_backoff_doubles_and_caps(tmp_path: Path) -> None:
    poller = _poller(
        tmp_path,
        [failed()] * 5,
        poll_live_seconds=10,
        poll_max_backoff_seconds=25,
    )
    assert await poller.tick() == 10
    assert await poller.tick() == 20
    assert await poller.tick() == 25
    assert await poller.tick() == 25


async def test_backoff_resets_after_success(tmp_path: Path) -> None:
    poller = _poller(tmp_path, [failed(), failed(), ok({})])
    assert await poller.tick() == 10
    assert await poller.tick() == 20
    assert await poller.tick() == 60  # idle cadence after success
    poller.client = FakeClient([failed()])
    assert await poller.tick() == 10  # backoff restarts from base


async def test_intervals_come_from_settings(tmp_path: Path) -> None:
    poller = _poller(tmp_path, [ok({})], poll_idle_seconds=7, poll_live_seconds=3)
    assert await poller.tick() == 7
    poller.client = FakeClient([failed()])
    assert await poller.tick() == 3


class _StopLoop(Exception):
    pass


async def test_run_loops_and_sleeps_between_ticks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    poller = _poller(tmp_path, [], poll_idle_seconds=7)
    delays: list[float] = []

    async def fake_sleep(delay: float) -> None:
        delays.append(delay)
        if len(delays) >= 3:
            raise _StopLoop()

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    with pytest.raises(_StopLoop):
        await poller.run()
    assert delays == [7, 7, 7]
    assert poller.client.calls == 3


def test_run_starts_uvicorn_on_configured_port(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: dict[str, Any] = {}

    def fake_uvicorn_run(app: object, **kwargs: Any) -> None:
        calls["app"] = app
        calls.update(kwargs)

    monkeypatch.setattr(main.uvicorn, "run", fake_uvicorn_run)
    monkeypatch.setattr(main, "preferences_path", lambda: tmp_path / "prefs.json")
    monkeypatch.setenv("RIOT_API_KEY", "placeholder")
    monkeypatch.setenv("NEXUS_PORT", "8123")
    monkeypatch.setenv("STORAGE_BACKEND", "json")

    main.run()

    assert calls["port"] == 8123
    assert calls["host"] == "127.0.0.1"
    assert calls["app"] is not None
