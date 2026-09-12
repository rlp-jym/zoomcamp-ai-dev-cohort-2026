"""Raw Riot payloads -> contract-shaped scoreboard state.

Pure functions only: no HTTP, no disk, no clock reads. Time enters as
arguments (frame timestamps come from the data itself; ``build_state``
takes ``now``) or lives in the caller-owned ``GameContext``. Unknown is
``None`` — never ``0``, ``""``, or ``NaN``. A missing field yields partial
state, never an exception (a wholly unusable payload yields ``None`` for
that tick; the poller retains last-known state).

Documented choices (see also the step 5 report):

1. ``clockSeconds``: the feed has no game-clock field; ``rfc460Timestamp``
   is a wall-clock capture time (verified: matches recording wall time,
   monotonic, does not start near zero). The clock is the wall-clock delta
   between the latest frame timestamp and a per-game anchor stored in
   ``GameContext`` (first frame observed for that game). Exact when the
   poller observes game start; understates when attaching mid-game.
2. ``champion``: ``championId`` already arrives as a name string
   (e.g. "Olaf"), passed through verbatim. No lookup table exists or is
   needed. ``None`` when absent.
3. ``items``: the feed carries no item data at all, so every player gets
   ``[]`` (the contract requires a non-nullable array). Real data gap.
4. ``color``: no source carries team colors, so always ``None``.
5. ``home`` = blue side, ``away`` = red side, resolved per game from the
   in-progress (or next) game's ``sides`` entries in event details. Sides
   swap between games (game 2 had T1 on blue) but are fixed at draft, so
   this is stable for the whole game.
6. ``objectiveTimers``: derived statefully. A count increase between ticks
   records a kill at that frame's wall time; the timer counts down the
   known respawn interval (dragon 5:00, baron 6:00; first spawns at 5:00
   and 20:00 of game clock). ``None`` when unknown or already spawned.
7. ``normalize_event_details`` returns a ``MatchState`` with
   ``game_number=None`` when the match is usable but no game is in
   progress (the between-games screen needs series score and teams, specs
   §8.2). ``None`` only when the match block itself is unusable.
8. ``normalize_window`` maps the LAST inner frame (most current state).
9. ``diff_frames`` is gone: the contract has no events field and the
   frontend spec forbids event callouts, so it had no consumer.
10. Schema-non-nullable fallbacks: ``SeriesScore`` requires ints, so a
    missing ``gameWins`` falls back to ``0``; ``Team`` requires ``name``
    and ``code`` strings, so missing values fall back to ``""``. Both are
    reliably present in practice; the fallbacks only keep the keys present
    per the contract's never-omit rule.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError

from nexus.riot import models

logger = logging.getLogger(__name__)

DRAGON_FIRST_SPAWN_SECONDS = 300
DRAGON_RESPAWN_SECONDS = 300
BARON_FIRST_SPAWN_SECONDS = 1200
BARON_RESPAWN_SECONDS = 360


@dataclass
class TeamState:
    name: str
    code: str
    logo: str | None
    color: str | None = None


@dataclass
class SideInts:
    home: int | None
    away: int | None


@dataclass
class SideDragonLists:
    home: list[str] | None
    away: list[str] | None


@dataclass
class PlayerState:
    role: str
    champion: str | None
    kills: int | None
    deaths: int | None
    assists: int | None
    cs: int | None
    items: list[int]
    participant_id: int | None = None


@dataclass
class MatchState:
    match_id: str
    best_of: int | None
    game_number: int | None
    next_game_number: int | None
    series_home: int
    series_away: int
    home: TeamState
    away: TeamState
    blue_team_id: str | None
    red_team_id: str | None


@dataclass
class GameState:
    clock_seconds: int | None
    kills: SideInts
    gold: SideInts
    towers: SideInts
    dragons: SideDragonLists
    barons: SideInts
    players_home: list[PlayerState]
    players_away: list[PlayerState]
    dragon_timer: int | None
    baron_timer: int | None


@dataclass
class GameContext:
    """Per-game accumulating state owned by the poller (step 6).

    ``anchor_key`` is (match_id, game_number); any change resets the rest.
    ``game_start_wall`` anchors the derived game clock. The ``last_*``
    fields track objective counts and kill wall times for respawn timers.
    """

    anchor_key: tuple[str, int] | None = None
    game_start_wall: datetime | None = None
    last_dragon_total: int | None = None
    last_baron_total: int | None = None
    last_dragon_kill: datetime | None = None
    last_baron_kill: datetime | None = None

    def reset(self, key: tuple[str, int]) -> None:
        self.anchor_key = key
        self.game_start_wall = None
        self.last_dragon_total = None
        self.last_baron_total = None
        self.last_dragon_kill = None
        self.last_baron_kill = None


def _str_list(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    return [item for item in value if isinstance(item, str)]


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        stamp = value
        if stamp.endswith("Z"):
            stamp = stamp[:-1] + "+00:00"
        return datetime.fromisoformat(stamp)
    except ValueError:
        return None


def _format_time(now: datetime) -> str:
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    if now.utcoffset() == timedelta(0):
        return now.strftime("%Y-%m-%dT%H:%M:%SZ")
    return now.isoformat()


def _wins(entry: models.MatchTeamEntry) -> int:
    if entry.result is not None and isinstance(entry.result.gameWins, int):
        return entry.result.gameWins
    return 0


def _team_state(entry: models.MatchTeamEntry) -> TeamState:
    name = entry.name if isinstance(entry.name, str) else ""
    code = entry.code if isinstance(entry.code, str) else ""
    logo = entry.image if isinstance(entry.image, str) else None
    return TeamState(name=name, code=code, logo=logo, color=None)


def normalize_event_details(raw: dict[str, Any]) -> MatchState | None:
    """Map an event_details response to the Match portion of state.

    Returns a MatchState with ``game_number=None`` when the match is
    usable but no game is in progress (between games). Returns ``None``
    only when the match block itself is missing or unusable.
    """
    if not isinstance(raw, dict):
        return None
    try:
        details = models.EventDetails.model_validate(raw)
    except ValidationError as exc:
        logger.debug("event_details failed validation: %s", exc)
        return None
    event = details.data.event if details.data is not None else None
    if event is None or event.match is None:
        return None
    match = event.match
    teams = match.teams or []
    if len(teams) < 2:
        return None
    games = match.games or []
    live = next((g for g in games if g.state == "inProgress"), None)
    anchor_game: models.GameEntry | None
    if live is not None:
        game_number = live.number if isinstance(live.number, int) else None
        next_game_number = None
        anchor_game = live
    else:
        game_number = None
        unstarted = [
            g.number
            for g in games
            if g.state == "unstarted" and isinstance(g.number, int)
        ]
        next_game_number = min(unstarted) if unstarted else None
        anchor_game = next(
            (g for g in games if g.state == "unstarted"),
            None,
        )
    blue_id: str | None = None
    red_id: str | None = None
    if anchor_game is not None and anchor_game.teams:
        for side_entry in anchor_game.teams:
            if side_entry.side == "blue":
                blue_id = side_entry.id
            elif side_entry.side == "red":
                red_id = side_entry.id
    by_id = {t.id: t for t in teams if t.id is not None}
    home_entry = by_id.get(blue_id) if blue_id is not None else None
    away_entry = by_id.get(red_id) if red_id is not None else None
    if home_entry is None or away_entry is None:
        # Sides missing or unresolvable: fall back to listing order.
        home_entry, away_entry = teams[0], teams[1]
        blue_id = home_entry.id
        red_id = away_entry.id
    best_of: int | None = None
    if match.strategy is not None and isinstance(match.strategy.count, int):
        best_of = match.strategy.count
    match_id = event.id if isinstance(event.id, str) else ""
    return MatchState(
        match_id=match_id,
        best_of=best_of,
        game_number=game_number,
        next_game_number=next_game_number,
        series_home=_wins(home_entry),
        series_away=_wins(away_entry),
        home=_team_state(home_entry),
        away=_team_state(away_entry),
        blue_team_id=blue_id,
        red_team_id=red_id,
    )


def _meta_map(
    metadata: models.TeamMetadata | None,
) -> dict[int, tuple[str | None, str | None]]:
    out: dict[int, tuple[str | None, str | None]] = {}
    entries = metadata.participantMetadata if metadata is not None else None
    for meta in entries or []:
        if meta.participantId is not None:
            out[meta.participantId] = (meta.role, meta.championId)
    return out


def _map_player(
    participant: models.WindowParticipant,
    meta: tuple[str | None, str | None] | None,
) -> PlayerState:
    role, champion = meta if meta is not None else (None, None)
    return PlayerState(
        role=role if isinstance(role, str) and role else "UNKNOWN",
        champion=champion if isinstance(champion, str) else None,
        kills=participant.kills,
        deaths=participant.deaths,
        assists=participant.assists,
        cs=participant.creepScore,
        items=[],
        participant_id=participant.participantId,
    )


def _map_side_players(
    team: models.WindowTeam | None,
    metadata: models.TeamMetadata | None,
) -> list[PlayerState]:
    if team is None:
        return []
    metas = _meta_map(metadata)
    players: list[PlayerState] = []
    for participant in team.participants or []:
        meta = (
            metas.get(participant.participantId)
            if participant.participantId is not None
            else None
        )
        players.append(_map_player(participant, meta))
    players.sort(key=lambda p: (p.participant_id is None, p.participant_id or 0))
    return players


def _countdown(
    kill_at: datetime | None,
    now: datetime,
    interval: int,
) -> int | None:
    if kill_at is None:
        return None
    try:
        remaining = interval - int((now - kill_at).total_seconds())
    except TypeError:
        return None
    return remaining if remaining > 0 else None


def _objective_timers(
    ts: datetime,
    clock: int,
    blue: models.WindowTeam | None,
    red: models.WindowTeam | None,
    context: GameContext,
) -> tuple[int | None, int | None]:
    blue_dragons = _str_list(blue.dragons) if blue is not None else None
    red_dragons = _str_list(red.dragons) if red is not None else None
    if (
        blue is None
        or red is None
        or blue_dragons is None
        or red_dragons is None
        or not isinstance(blue.barons, int)
        or not isinstance(red.barons, int)
    ):
        return None, None
    dragon_total = len(blue_dragons) + len(red_dragons)
    baron_total = blue.barons + red.barons
    if context.last_dragon_total is None:
        context.last_dragon_total = dragon_total
    elif dragon_total > context.last_dragon_total:
        context.last_dragon_total = dragon_total
        context.last_dragon_kill = ts
    elif dragon_total < context.last_dragon_total:
        context.last_dragon_total = dragon_total
        context.last_dragon_kill = None
    if context.last_baron_total is None:
        context.last_baron_total = baron_total
    elif baron_total > context.last_baron_total:
        context.last_baron_total = baron_total
        context.last_baron_kill = ts
    elif baron_total < context.last_baron_total:
        context.last_baron_total = baron_total
        context.last_baron_kill = None
    dragon_timer = _countdown(context.last_dragon_kill, ts, DRAGON_RESPAWN_SECONDS)
    if (
        dragon_timer is None
        and context.last_dragon_kill is None
        and dragon_total == 0
        and clock < DRAGON_FIRST_SPAWN_SECONDS
    ):
        dragon_timer = DRAGON_FIRST_SPAWN_SECONDS - clock
    baron_timer = _countdown(context.last_baron_kill, ts, BARON_RESPAWN_SECONDS)
    if (
        baron_timer is None
        and context.last_baron_kill is None
        and baron_total == 0
        and clock < BARON_FIRST_SPAWN_SECONDS
    ):
        baron_timer = BARON_FIRST_SPAWN_SECONDS - clock
    return dragon_timer, baron_timer


def _side_ints(
    blue: models.WindowTeam | None,
    red: models.WindowTeam | None,
    field: str,
) -> SideInts:
    home: int | None = None
    away: int | None = None
    if blue is not None:
        value = getattr(blue, field, None)
        home = value if isinstance(value, int) and not isinstance(value, bool) else None
    if red is not None:
        value = getattr(red, field, None)
        away = value if isinstance(value, int) and not isinstance(value, bool) else None
    return SideInts(home=home, away=away)


def normalize_window(
    raw: dict[str, Any], match: MatchState, context: GameContext
) -> GameState | None:
    """Map a window response to the Game portion of state.

    Maps the last (most current) inner frame, blue side to home and red
    side to away (see module docstring choice 5). Returns ``None`` if
    the frame has no usable data. Advances ``context`` (clock anchor and
    objective kill times) as a side effect.
    """
    if not isinstance(raw, dict):
        return None
    try:
        window = models.WindowFrame.model_validate(raw)
    except ValidationError as exc:
        logger.debug("window failed validation: %s", exc)
        return None
    inners = window.frames or []
    if not inners:
        return None
    frame = inners[-1]
    if frame.blueTeam is None and frame.redTeam is None:
        return None
    key = (match.match_id, match.game_number or 0)
    if context.anchor_key != key:
        context.reset(key)
    ts = _parse_time(frame.rfc460Timestamp)
    clock: int | None = None
    if ts is not None:
        if context.game_start_wall is None:
            context.game_start_wall = ts
        try:
            clock = max(0, int((ts - context.game_start_wall).total_seconds()))
        except TypeError:
            clock = None
    blue = frame.blueTeam
    red = frame.redTeam
    metadata = window.gameMetadata
    if ts is not None and clock is not None:
        dragon_timer, baron_timer = _objective_timers(ts, clock, blue, red, context)
    else:
        dragon_timer, baron_timer = None, None
    return GameState(
        clock_seconds=clock,
        kills=_side_ints(blue, red, "totalKills"),
        gold=_side_ints(blue, red, "totalGold"),
        towers=_side_ints(blue, red, "towers"),
        dragons=SideDragonLists(
            home=_str_list(blue.dragons) if blue is not None else None,
            away=_str_list(red.dragons) if red is not None else None,
        ),
        barons=_side_ints(blue, red, "barons"),
        players_home=_map_side_players(
            blue, metadata.blueTeamMetadata if metadata is not None else None
        ),
        players_away=_map_side_players(
            red, metadata.redTeamMetadata if metadata is not None else None
        ),
        dragon_timer=dragon_timer,
        baron_timer=baron_timer,
    )


def _player_dict(player: PlayerState) -> dict[str, Any]:
    return {
        "role": player.role,
        "champion": player.champion,
        "kills": player.kills,
        "deaths": player.deaths,
        "assists": player.assists,
        "cs": player.cs,
        "items": list(player.items),
    }


def _team_dict(team: TeamState) -> dict[str, Any]:
    return {
        "name": team.name,
        "code": team.code,
        "logo": team.logo,
        "color": team.color,
    }


def build_state(
    match: MatchState | None,
    game: GameState | None,
    stale: bool,
    now: datetime,
) -> dict[str, Any]:
    """Combine pieces into the full /api/state payload.

    ``live`` requires both match and game; match without game is
    ``between_games``; neither is ``idle``. Every nullable leaf is present
    with ``null`` when unknown; keys are never omitted.
    """
    if match is not None and game is not None:
        status = "live"
    elif match is not None:
        status = "between_games"
    else:
        status = "idle"
    match_dict: dict[str, Any] | None = None
    if match is not None:
        match_dict = {
            "id": match.match_id,
            "bestOf": match.best_of,
            "gameNumber": match.game_number if status == "live" else None,
            "nextGameNumber": (
                match.next_game_number if status == "between_games" else None
            ),
            "seriesScore": {"home": match.series_home, "away": match.series_away},
            "teams": {"home": _team_dict(match.home), "away": _team_dict(match.away)},
        }
    game_dict: dict[str, Any] | None = None
    if status == "live" and game is not None:
        game_dict = {
            "clockSeconds": game.clock_seconds,
            "kills": {"home": game.kills.home, "away": game.kills.away},
            "gold": {"home": game.gold.home, "away": game.gold.away},
            "towers": {"home": game.towers.home, "away": game.towers.away},
            "dragons": {"home": game.dragons.home, "away": game.dragons.away},
            "barons": {"home": game.barons.home, "away": game.barons.away},
            "players": {
                "home": [_player_dict(p) for p in game.players_home],
                "away": [_player_dict(p) for p in game.players_away],
            },
            "objectiveTimers": {
                "dragon": game.dragon_timer,
                "baron": game.baron_timer,
            },
        }
    return {
        "status": status,
        "stale": stale,
        "lastUpdated": _format_time(now),
        "match": match_dict,
        "game": game_dict,
    }
