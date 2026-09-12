"""Tests for riot/normalize.py — raw fixtures in, contract-shaped state out.

Every test loads real recorded data from tests/fixtures/ (never the live
API). Synthetic inputs appear only where the task requires them: editing a
fixture's game states to simulate between-games, and deleting keys to prove
missing fields degrade instead of raising.
"""

import json
import math
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from nexus.riot.normalize import (
    BARON_FIRST_SPAWN_SECONDS,
    DRAGON_RESPAWN_SECONDS,
    GameContext,
    build_state,
    normalize_event_details,
    normalize_window,
)

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def live_match() -> Any:
    match = normalize_event_details(load("event_details.json"))
    assert match is not None
    return match


def _assert_no_nan(value: Any) -> None:
    if is_dataclass(value) and not isinstance(value, type):
        value = asdict(value)
    if isinstance(value, float):
        assert not math.isnan(value), "NaN leaked into normalized state"
    elif isinstance(value, dict):
        for item in value.values():
            _assert_no_nan(item)
    elif isinstance(value, list):
        for item in value:
            _assert_no_nan(item)


# --- normalize_event_details ---


def test_event_details_teams_series_bestof_game() -> None:
    match = live_match()
    assert match.match_id == "117030752644841637"
    assert match.home.code == "HLE"
    assert match.home.name == "Hanwha Life Esports"
    assert match.away.code == "T1"
    assert match.series_home == 2
    assert match.series_away == 0
    assert match.best_of == 5
    assert match.game_number == 3


def test_event_details_home_is_blue_side() -> None:
    match = live_match()
    # Game 3 has HLE on blue; game 2 had T1 on blue, so this mapping must
    # come from the in-progress game's sides, not from team order.
    assert match.blue_team_id == "100205573496804586"
    assert match.red_team_id == "98767991853197861"
    assert match.home.code == "HLE"
    assert match.away.code == "T1"


def test_event_details_team_color_is_null() -> None:
    match = live_match()
    assert match.home.color is None
    assert match.away.color is None
    assert match.home.logo is not None
    assert "hle" in match.home.logo


def test_event_details_no_in_progress_game_gives_between_games() -> None:
    raw = load("event_details.json")
    for game in raw["data"]["event"]["match"]["games"]:
        if game["state"] == "inProgress":
            game["state"] = "unstarted"
    match = normalize_event_details(raw)
    assert match is not None
    assert match.game_number is None
    assert match.next_game_number == 3
    assert match.series_home == 2


def test_event_details_returns_none_without_match() -> None:
    assert normalize_event_details({}) is None
    assert normalize_event_details({"data": {}}) is None
    assert normalize_event_details({"data": {"event": {}}}) is None
    raw = load("event_details.json")
    del raw["data"]["event"]["match"]["teams"]
    assert normalize_event_details(raw) is None


# --- normalize_window against window_single.json ---


def test_window_single_sides_and_totals() -> None:
    raw = load("window_single.json")
    last = raw["frames"][-1]
    game = normalize_window(raw, live_match(), GameContext())
    assert game is not None
    assert game.kills.home == last["blueTeam"]["totalKills"]
    assert game.kills.away == last["redTeam"]["totalKills"]
    assert game.gold.home == last["blueTeam"]["totalGold"]
    assert game.gold.away == last["redTeam"]["totalGold"]
    assert game.towers.home == last["blueTeam"]["towers"]
    assert game.towers.away == last["redTeam"]["towers"]
    assert game.barons.home == last["blueTeam"]["barons"]
    assert game.barons.away == last["redTeam"]["barons"]
    assert game.dragons.home == last["blueTeam"]["dragons"]
    assert game.dragons.away == last["redTeam"]["dragons"]


def test_window_single_players() -> None:
    raw = load("window_single.json")
    last = raw["frames"][-1]
    game = normalize_window(raw, live_match(), GameContext())
    assert game is not None
    assert len(game.players_home) == 5
    assert len(game.players_away) == 5
    zeus = game.players_home[0]
    assert zeus.role == "top"
    # championId arrives as a name string; passed through verbatim.
    assert zeus.champion == "Olaf"
    ref = last["blueTeam"]["participants"][0]
    assert zeus.kills == ref["kills"]
    assert zeus.deaths == ref["deaths"]
    assert zeus.assists == ref["assists"]
    assert zeus.cs == ref["creepScore"]
    # The feed carries no items; the schema requires an array, so [].
    assert zeus.items == []
    roles = {p.role for p in game.players_home + game.players_away}
    assert roles == {"top", "jungle", "mid", "bottom", "support"}


def test_window_missing_side_degrades_to_partial() -> None:
    raw = load("window_single.json")
    del raw["frames"][-1]["blueTeam"]
    game = normalize_window(raw, live_match(), GameContext())
    assert game is not None
    assert game.kills.home is None
    assert game.gold.home is None
    assert game.players_home == []
    assert game.kills.away is not None


def test_window_missing_participant_field_is_null() -> None:
    raw = load("window_single.json")
    del raw["frames"][-1]["blueTeam"]["participants"][0]["creepScore"]
    game = normalize_window(raw, live_match(), GameContext())
    assert game is not None
    assert game.players_home[0].cs is None
    assert game.players_home[0].kills is not None


def test_window_returns_none_without_usable_data() -> None:
    match = live_match()
    assert normalize_window({}, match, GameContext()) is None
    assert normalize_window({"frames": []}, match, GameContext()) is None
    assert normalize_window({"frames": [{}]}, match, GameContext()) is None
    assert normalize_window([], match, GameContext()) is None  # type: ignore[arg-type]


# --- normalize_window against window_sequence.json ---


def test_window_sequence_all_frames_normalize_cleanly() -> None:
    seq = load("window_sequence.json")
    assert len(seq) == 30
    match = live_match()
    ctx = GameContext()
    for entry in seq:
        game = normalize_window(entry["response"], match, ctx)
        assert game is not None
        assert game.clock_seconds is not None and game.clock_seconds >= 0
        assert game.kills.home is not None and game.kills.away is not None
        assert game.gold.home is not None and game.gold.away is not None
        assert len(game.players_home) == 5
        assert len(game.players_away) == 5
        _assert_no_nan(game)


def test_window_sequence_totals_never_go_backward() -> None:
    seq = load("window_sequence.json")
    match = live_match()
    ctx = GameContext()
    games = [normalize_window(e["response"], match, ctx) for e in seq]
    assert all(g is not None for g in games)
    # File order is newest-first; walk oldest-first and require monotonicity.
    prev = None
    for game in reversed(games):
        assert game is not None
        if prev is not None:
            assert game.kills.home is not None and prev.kills.home is not None
            assert game.kills.home >= prev.kills.home
            assert game.kills.away is not None and prev.kills.away is not None
            assert game.kills.away >= prev.kills.away
            assert game.gold.home is not None and prev.gold.home is not None
            assert game.gold.home >= prev.gold.home
            assert game.towers.home is not None and prev.towers.home is not None
            assert game.towers.home >= prev.towers.home
        prev = game


# --- GameContext accumulation / objective timers ---


def test_objective_timers_first_spawn_countdown() -> None:
    seq = load("window_sequence.json")
    match = live_match()
    ctx = GameContext()
    oldest = seq[-1]
    game = normalize_window(oldest["response"], match, ctx)
    assert game is not None
    assert game.clock_seconds == 0
    # No baron taken yet and game clock < 20:00: countdown to first spawn.
    assert game.baron_timer == BARON_FIRST_SPAWN_SECONDS
    # Red already holds a dragon whose kill was never observed: unknown.
    assert game.dragon_timer is None


def test_objective_timers_dragon_take_resets_respawn() -> None:
    seq = load("window_sequence.json")
    match = live_match()
    ctx = GameContext()
    take_index = None
    prev_blue: list[str] | None = None
    for i, entry in enumerate(reversed(seq)):
        game = normalize_window(entry["response"], match, ctx)
        assert game is not None
        blue = game.dragons.home or []
        if prev_blue is not None and len(blue) > len(prev_blue):
            take_index = i
            assert game.dragon_timer == DRAGON_RESPAWN_SECONDS
        prev_blue = blue
    assert take_index is not None, "expected a blue dragon take in the sequence"


def test_game_context_resets_on_new_game() -> None:
    raw = load("window_single.json")
    match = live_match()
    ctx = GameContext()
    first = normalize_window(raw, match, ctx)
    assert first is not None
    second = normalize_window(raw, match, ctx)
    assert second is not None
    assert second.clock_seconds == first.clock_seconds
    match.game_number = 4
    restarted = normalize_window(raw, match, ctx)
    assert restarted is not None
    assert restarted.clock_seconds == 0


# --- build_state ---


def test_build_state_live() -> None:
    match = live_match()
    game = normalize_window(load("window_single.json"), match, GameContext())
    assert game is not None
    now = datetime(2026, 9, 12, 7, 51, 0, tzinfo=UTC)
    state = build_state(match, game, False, now)
    assert state["status"] == "live"
    assert state["stale"] is False
    assert state["lastUpdated"] == "2026-09-12T07:51:00Z"
    assert state["match"] is not None
    assert state["match"]["id"] == "117030752644841637"
    assert state["match"]["gameNumber"] == 3
    assert state["match"]["nextGameNumber"] is None
    assert state["match"]["seriesScore"] == {"home": 2, "away": 0}
    assert state["match"]["teams"]["home"]["code"] == "HLE"
    assert state["match"]["teams"]["away"]["code"] == "T1"
    assert state["game"] is not None
    assert state["game"]["objectiveTimers"].keys() == {"dragon", "baron"}
    _assert_no_nan(state)


def test_build_state_between_games() -> None:
    raw = load("event_details.json")
    for game in raw["data"]["event"]["match"]["games"]:
        if game["state"] == "inProgress":
            game["state"] = "unstarted"
    match = normalize_event_details(raw)
    assert match is not None
    now = datetime(2026, 9, 12, 8, 0, 0, tzinfo=UTC)
    state = build_state(match, None, False, now)
    assert state["status"] == "between_games"
    assert state["game"] is None
    assert state["match"] is not None
    assert state["match"]["gameNumber"] is None
    assert state["match"]["nextGameNumber"] == 3
    assert state["match"]["seriesScore"] == {"home": 2, "away": 0}


def test_build_state_idle_and_stale() -> None:
    now = datetime(2026, 9, 12, 8, 0, 0, tzinfo=UTC)
    state = build_state(None, None, True, now)
    assert state["status"] == "idle"
    assert state["stale"] is True
    assert state["match"] is None
    assert state["game"] is None


def test_build_state_game_without_match_is_idle() -> None:
    match = live_match()
    game = normalize_window(load("window_single.json"), match, GameContext())
    now = datetime(2026, 9, 12, 8, 0, 0, tzinfo=UTC)
    state = build_state(None, game, False, now)
    assert state["status"] == "idle"
    assert state["match"] is None
    assert state["game"] is None


def test_build_state_key_sets_match_openapi() -> None:
    match = live_match()
    game = normalize_window(load("window_single.json"), match, GameContext())
    assert game is not None
    now = datetime(2026, 9, 12, 7, 51, 0, tzinfo=UTC)
    state = build_state(match, game, False, now)
    assert set(state.keys()) == {"status", "stale", "lastUpdated", "match", "game"}
    assert set(state["match"].keys()) == {
        "id",
        "bestOf",
        "gameNumber",
        "nextGameNumber",
        "seriesScore",
        "teams",
    }
    assert set(state["game"].keys()) == {
        "clockSeconds",
        "kills",
        "gold",
        "towers",
        "dragons",
        "barons",
        "players",
        "objectiveTimers",
    }
    player = state["game"]["players"]["home"][0]
    assert set(player.keys()) == {
        "role",
        "champion",
        "kills",
        "deaths",
        "assists",
        "cs",
        "items",
    }
    # Nullable leaves are present as null, never omitted.
    assert "color" in state["match"]["teams"]["home"]
    assert state["match"]["teams"]["home"]["color"] is None


def test_build_state_required_values_never_null() -> None:
    match = live_match()
    game = normalize_window(load("window_single.json"), match, GameContext())
    assert game is not None
    now = datetime(2026, 9, 12, 7, 51, 0, tzinfo=UTC)
    state = build_state(match, game, False, now)
    assert isinstance(state["status"], str)
    assert isinstance(state["stale"], bool)
    assert isinstance(state["lastUpdated"], str)
    for side in ("home", "away"):
        team = state["match"]["teams"][side]
        assert team["name"] and team["code"]
        for player in state["game"]["players"][side]:
            assert player["role"]
            assert isinstance(player["items"], list)
