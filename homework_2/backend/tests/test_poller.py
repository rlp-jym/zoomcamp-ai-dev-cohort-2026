"""Tests for the poller loop (root AGENTS.md §4 tick, §6 intervals).

The poller takes a fake client: no HTTP here. Live-flow tests feed real
recorded fixtures through the fake; only game-state edits (to simulate
between-games or a game change) are synthetic. A failed fetch never
clears values but flips the stale flag (specs §8.3, FR-18).
"""

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from nexus import main
from nexus.config import Settings
from nexus.poller import Poller
from nexus.riot.client import FetchResult
from nexus.state import AppState, idle_state

MATCH_ID = "117030752644841637"
GAME3_ID = "117030752644841640"
GAME4_ID = "117030752644841641"

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def ok(data: Any) -> FetchResult:
    return FetchResult(data=data, ok=True)


def no_data() -> FetchResult:
    """HTTP 204: success with nothing to report."""
    return FetchResult(data=None, ok=True)


def failed() -> FetchResult:
    """A fetch that failed (403, 500, timeout, bad JSON)."""
    return FetchResult(data=None, ok=False)


class FakeClient:
    """Canned per-endpoint scripts of FetchResults; Exceptions raise."""

    def __init__(
        self,
        script: list[Any],
        event_script: list[Any] | None = None,
        window_script: list[Any] | None = None,
    ) -> None:
        self._script = list(script)
        self._event_script = list(event_script or [])
        self._window_script = list(window_script or [])
        self.calls = 0
        self.live_calls = 0
        self.event_calls: list[str] = []
        self.window_calls: list[tuple[str, str]] = []

    def _next(self, script: list[Any], default: FetchResult) -> FetchResult:
        if not script:
            return default
        action = script.pop(0)
        if isinstance(action, Exception):
            raise action
        return action

    async def get_live(self) -> FetchResult:
        self.calls += 1
        self.live_calls += 1
        return self._next(self._script, ok({}))

    async def get_event_details(self, match_id: str) -> FetchResult:
        self.event_calls.append(match_id)
        return self._next(self._event_script, ok({}))

    async def get_window(self, game_id: str, starting_time: str) -> FetchResult:
        self.window_calls.append((game_id, starting_time))
        return self._next(self._window_script, ok({}))


def _settings(**overrides: Any) -> Settings:
    return Settings(**overrides)


def _poller(
    tmp_path: Path,
    script: list[Any],
    event_script: list[Any] | None = None,
    window_script: list[Any] | None = None,
    get_pinned: Callable[[], str | None] | None = None,
    **overrides: Any,
) -> Poller:
    return Poller(
        client=FakeClient(script, event_script, window_script),
        store=AppState(),
        settings=_settings(**overrides),
        get_pinned=get_pinned,
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


def _between_games_event() -> Any:
    raw = fixture("event_details.json")
    for game in raw["data"]["event"]["match"]["games"]:
        if game["state"] == "inProgress":
            game["state"] = "unstarted"
    return raw


def _next_game_event() -> Any:
    raw = fixture("event_details.json")
    for game in raw["data"]["event"]["match"]["games"]:
        if game["number"] == 3:
            game["state"] = "completed"
        if game["number"] == 4:
            game["state"] = "inProgress"
    return raw


async def test_tick_live_flow_sets_live_state(tmp_path: Path) -> None:
    poller = _poller(
        tmp_path,
        [ok(fixture("get_live.json"))],
        event_script=[ok(fixture("event_details.json"))],
        window_script=[ok(fixture("window_single.json"))],
    )
    assert await poller.tick() == 10
    state = poller.store.get()
    assert state["status"] == "live"
    assert state["stale"] is False
    assert state["match"] is not None
    assert state["match"]["id"] == MATCH_ID
    assert state["match"]["gameNumber"] == 3
    assert state["game"] is not None
    last = fixture("window_single.json")["frames"][-1]
    assert state["game"]["kills"]["home"] == last["blueTeam"]["totalKills"]
    assert state["game"]["kills"]["away"] == last["redTeam"]["totalKills"]
    assert len(state["game"]["players"]["home"]) == 5


async def test_tick_uses_offset_starting_time(tmp_path: Path) -> None:
    poller = _poller(
        tmp_path,
        [ok(fixture("get_live.json"))],
        event_script=[ok(fixture("event_details.json"))],
        window_script=[ok(fixture("window_single.json"))],
    )
    await poller.tick()
    assert isinstance(poller.client, FakeClient)
    assert len(poller.client.window_calls) == 1
    game_id, starting_time = poller.client.window_calls[0]
    assert game_id == GAME3_ID
    # Offset ~40s into the past, still 10s-aligned: never "now", so the
    # feed's ~20s anti-spoiler buffer cannot 400 it.
    assert starting_time.endswith("0.000Z")
    age = (datetime.now(UTC) - datetime.fromisoformat(starting_time)).total_seconds()
    assert 25 <= age <= 90


async def test_tick_between_games_when_no_game_in_progress(
    tmp_path: Path,
) -> None:
    poller = _poller(
        tmp_path,
        [ok(fixture("get_live.json"))],
        event_script=[ok(_between_games_event())],
    )
    assert await poller.tick() == 30
    state = poller.store.get()
    assert state["status"] == "between_games"
    assert state["game"] is None
    assert state["match"] is not None
    assert state["match"]["gameNumber"] is None
    assert state["match"]["nextGameNumber"] == 3
    assert isinstance(poller.client, FakeClient)
    assert poller.client.window_calls == []


async def test_tick_idle_when_no_live_event(tmp_path: Path) -> None:
    poller = _poller(tmp_path, [ok({"data": {"schedule": {"events": []}}})])
    assert await poller.tick() == 60
    state = poller.store.get()
    assert state["status"] == "idle"
    assert state["match"] is None
    assert state["game"] is None


async def test_tick_window_error_keeps_live_values(tmp_path: Path) -> None:
    poller = _poller(
        tmp_path,
        [ok(fixture("get_live.json")), ok(fixture("get_live.json"))],
        event_script=[
            ok(fixture("event_details.json")),
            ok(fixture("event_details.json")),
        ],
        window_script=[ok(fixture("window_single.json")), failed()],
    )
    assert await poller.tick() == 10
    before = poller.store.get()
    assert before["status"] == "live"
    assert await poller.tick() == 10  # backoff, not the live cadence
    after = poller.store.get()
    assert after["status"] == "live"
    assert after["stale"] is True
    assert after["game"] == before["game"]
    assert after["lastUpdated"] == before["lastUpdated"]


async def test_tick_resets_context_on_game_change(tmp_path: Path) -> None:
    poller = _poller(
        tmp_path,
        [ok(fixture("get_live.json")), ok(fixture("get_live.json"))],
        event_script=[
            ok(fixture("event_details.json")),
            ok(_next_game_event()),
        ],
        window_script=[
            ok(fixture("window_single.json")),
            ok(fixture("window_single.json")),
        ],
    )
    await poller.tick()
    assert poller._game_key == (MATCH_ID, 3)
    first_context = poller._context
    await poller.tick()
    assert poller._game_key == (MATCH_ID, 4)
    # Same window payload both ticks, so timestamps match: the reset is
    # proven by context identity, not by clock values.
    assert poller._context is not first_context
    assert poller._context.anchor_key == (MATCH_ID, 4)
    assert isinstance(poller.client, FakeClient)
    assert poller.client.window_calls[1][0] == GAME4_ID
    assert poller.store.get()["status"] == "live"


async def test_tick_pinned_match_skips_get_live(tmp_path: Path) -> None:
    poller = _poller(
        tmp_path,
        [],
        event_script=[ok(fixture("event_details.json"))],
        window_script=[ok(fixture("window_single.json"))],
        get_pinned=lambda: MATCH_ID,
    )
    assert await poller.tick() == 10
    assert isinstance(poller.client, FakeClient)
    assert poller.client.live_calls == 0
    assert poller.client.event_calls == [MATCH_ID]
    assert poller.store.get()["status"] == "live"


async def test_tick_event_details_failure_marks_stale(tmp_path: Path) -> None:
    poller = _poller(
        tmp_path,
        [ok(fixture("get_live.json"))],
        event_script=[failed()],
    )
    assert await poller.tick() == 10
    state = poller.store.get()
    assert state["stale"] is True


def test_live_mode_requires_a_client(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="live mode requires a Riot client"):
        Poller(client=None, store=AppState(), settings=_settings())


def test_replay_mode_requires_replay_data(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="requires replay data"):
        Poller(
            client=None,
            store=AppState(),
            settings=_settings(poll_source="replay", replay_file="x.json"),
        )


def test_live_mode_never_touches_replay_data(tmp_path: Path) -> None:
    poller = Poller(
        client=FakeClient([ok(fixture("get_live.json"))]),
        store=AppState(),
        settings=_settings(),
        replay={"frames": []},
    )
    assert poller._replay_frames == []
