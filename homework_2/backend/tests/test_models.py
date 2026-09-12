"""Tests for riot/models.py — pydantic shells over recorded Riot payloads.

Every test loads real recorded data from tests/fixtures/ (never the live
API). Models are tolerant: every non-essential field is optional and unknown
fields are kept, so a schema surprise degrades instead of raising.
"""

import json
from pathlib import Path
from typing import Any

from nexus.riot import models

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_window_frame_parses_recorded_fixture() -> None:
    frame = models.WindowFrame.model_validate(load("window_single.json"))
    assert frame.esportsGameId == "117030752644841640"
    assert frame.esportsMatchId == "117030752644841637"
    assert frame.frames is not None and len(frame.frames) > 0
    assert frame.gameMetadata is not None
    assert frame.gameMetadata.patchVersion == "16.16.809.3269"


def test_window_frame_participant_metadata() -> None:
    frame = models.WindowFrame.model_validate(load("window_single.json"))
    assert frame.gameMetadata is not None
    blue = frame.gameMetadata.blueTeamMetadata
    assert blue is not None
    assert blue.esportsTeamId == "100205573496804586"
    assert blue.participantMetadata is not None
    assert len(blue.participantMetadata) == 5
    first = blue.participantMetadata[0]
    assert first.participantId == 1
    assert first.role == "top"
    # championId arrives as a name string, not a numeric id (verified
    # against the recorded fixture) — no lookup table needed or wanted.
    assert first.championId == "Olaf"


def test_window_frame_inner_frame_shape() -> None:
    frame = models.WindowFrame.model_validate(load("window_single.json"))
    assert frame.frames is not None
    inner = frame.frames[0]
    assert inner.gameState == "in_game"
    assert inner.rfc460Timestamp is not None
    assert inner.blueTeam is not None and inner.redTeam is not None
    assert inner.blueTeam.totalKills == 3
    assert inner.blueTeam.totalGold == 20167
    assert inner.blueTeam.participants is not None
    assert len(inner.blueTeam.participants) == 5
    assert inner.blueTeam.participants[0].creepScore == 97


def test_window_frame_tolerates_missing_fields() -> None:
    assert models.WindowFrame.model_validate({}).frames is None
    partial = models.WindowFrame.model_validate({"esportsGameId": "x"})
    assert partial.esportsGameId == "x"
    assert partial.gameMetadata is None
    inner = models.WindowInnerFrame.model_validate({"gameState": "in_game"})
    assert inner.blueTeam is None and inner.rfc460Timestamp is None


def test_window_frame_keeps_unknown_fields() -> None:
    frame = models.WindowFrame.model_validate(
        {"esportsGameId": "x", "futureField": {"nested": [1, 2]}}
    )
    assert frame.model_extra is not None
    assert frame.model_extra["futureField"] == {"nested": [1, 2]}


def test_event_details_parses_recorded_fixture() -> None:
    details = models.EventDetails.model_validate(load("event_details.json"))
    assert details.data is not None
    event = details.data.event
    assert event is not None
    assert event.id == "117030752644841637"
    assert event.league is not None and event.league.slug == "lck"
    assert event.match is not None
    codes = [t.code for t in event.match.teams or []]
    assert codes == ["HLE", "T1"]
    assert event.match.strategy is not None
    assert event.match.strategy.count == 5
    assert event.match.games is not None
    assert len(event.match.games) == 5


def test_event_details_per_game_sides() -> None:
    details = models.EventDetails.model_validate(load("event_details.json"))
    assert details.data is not None
    assert details.data.event is not None
    assert details.data.event.match is not None
    games = details.data.event.match.games or []
    by_number = {g.number: g for g in games}
    # Sides swap between games (game 2 has T1 on blue), so side mapping
    # must be read per game, never hardcoded.
    live = by_number[3]
    assert live.state == "inProgress"
    sides = {t.id: t.side for t in live.teams or []}
    assert sides == {
        "100205573496804586": "blue",
        "98767991853197861": "red",
    }
    game2 = by_number[2]
    sides2 = {t.id: t.side for t in game2.teams or []}
    assert sides2["98767991853197861"] == "blue"


def test_event_details_tolerates_missing_fields() -> None:
    assert models.EventDetails.model_validate({}).data is None
    assert models.EventDetails.model_validate({"data": {}}).data is not None


def test_get_live_parses_recorded_fixture() -> None:
    live = models.GetLive.model_validate(load("get_live.json"))
    assert live.data is not None
    assert live.data.schedule is not None
    events = live.data.schedule.events or []
    assert len(events) == 1
    assert events[0].id == "117030752644841637"
    assert events[0].state == "inProgress"
    assert events[0].league is not None and events[0].league.name == "LCK"
    assert events[0].match is not None
    assert events[0].match.strategy is not None
    assert events[0].match.strategy.count == 5


def test_live_event_tolerates_missing_fields() -> None:
    assert models.LiveEvent.model_validate({}).id is None
    assert models.LiveEvent.model_validate({"state": "inProgress"}).state == (
        "inProgress"
    )
