"""Tests for poller replay mode (dev/demo only, not the product contract).

Replay mode makes no Riot calls: the parsed replay dict is handed to the
poller (main.run() loads the file once at startup), frames walk
oldest-first at one per tick, and the walk loops at the end. The sample
replay is real recorded data; only the tiny loop fixture is synthetic.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from nexus.config import Settings
from nexus.poller import REPLAY_INTERVAL_SECONDS, Poller
from nexus.state import AppState

REPLAY_PATH = (
    Path(__file__).parent.parent.parent / "replays" / "lck-2026-09-12-hle-vs-t1-g3.json"
)


def load_replay() -> Any:
    return json.loads(REPLAY_PATH.read_text(encoding="utf-8"))


def _replay_poller(replay: Any, **overrides: Any) -> Poller:
    settings = Settings(poll_source="replay", replay_file=str(REPLAY_PATH), **overrides)
    return Poller(client=None, store=AppState(), settings=settings, replay=replay)


def _tiny_replay() -> Any:
    full = load_replay()
    return {
        "match_id": full["match_id"],
        "game_id": full["game_id"],
        "event_details": full["event_details"],
        "frames": [full["frames"][50], full["frames"][49]],
    }


async def test_replay_loads_sample_file() -> None:
    poller = _replay_poller(load_replay())
    assert len(poller._replay_frames) == 140
    assert poller._replay_match is not None
    assert poller._replay_match.game_number == 3


async def test_replay_tick_is_live_without_client() -> None:
    poller = _replay_poller(load_replay())
    assert await poller.tick() == REPLAY_INTERVAL_SECONDS
    state = poller.store.get()
    assert state["status"] == "live"
    assert state["stale"] is False
    assert state["match"] is not None
    assert state["game"] is not None
    assert len(state["game"]["players"]["home"]) == 5


async def test_replay_walks_oldest_first() -> None:
    poller = _replay_poller(load_replay())
    await poller.tick()
    first_clock = poller.store.get()["game"]["clockSeconds"]
    await poller.tick()
    second_clock = poller.store.get()["game"]["clockSeconds"]
    assert first_clock == 0
    assert second_clock is not None and second_clock >= first_clock


async def test_replay_full_file_monotonic() -> None:
    poller = _replay_poller(load_replay())
    prev = None
    for _ in range(len(poller._replay_frames)):
        assert await poller.tick() == REPLAY_INTERVAL_SECONDS
        state = poller.store.get()
        assert state["status"] == "live"
        game = state["game"]
        assert game is not None
        if prev is not None:
            assert game["kills"]["home"] >= prev["kills"]["home"]
            assert game["kills"]["away"] >= prev["kills"]["away"]
            assert game["gold"]["home"] >= prev["gold"]["home"]
            assert game["gold"]["away"] >= prev["gold"]["away"]
            assert game["towers"]["home"] >= prev["towers"]["home"]
            assert game["towers"]["away"] >= prev["towers"]["away"]
        prev = game


async def test_replay_loops_at_end_of_frames() -> None:
    poller = _replay_poller(_tiny_replay())
    assert len(poller._replay_frames) == 2
    assert await poller.tick() == REPLAY_INTERVAL_SECONDS
    assert poller._replay_index == 1
    assert await poller.tick() == REPLAY_INTERVAL_SECONDS
    assert poller._replay_index == 0
    assert await poller.tick() == REPLAY_INTERVAL_SECONDS
    assert poller._replay_index == 1
    assert poller.store.get()["status"] == "live"


async def test_replay_resets_context_on_loop() -> None:
    poller = _replay_poller(_tiny_replay())
    await poller.tick()
    assert poller.store.get()["game"]["clockSeconds"] == 0
    await poller.tick()  # last frame; the walk wraps here
    assert poller._replay_index == 0
    await poller.tick()  # first frame again, on a fresh context
    assert poller.store.get()["game"]["clockSeconds"] == 0


def test_replay_rejects_empty_frames() -> None:
    replay = load_replay()
    replay["frames"] = []
    with pytest.raises(ValueError, match="no usable frames"):
        _replay_poller(replay)


def test_replay_rejects_missing_live_game() -> None:
    replay = load_replay()
    replay["event_details"] = {"data": {}}
    with pytest.raises(ValueError, match="no live game"):
        _replay_poller(replay)
