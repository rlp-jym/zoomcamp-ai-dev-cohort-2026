"""Pydantic models for raw Riot lolesports payloads.

Written against the recorded fixtures in tests/fixtures/, not against
guesses. Every field is optional and unknown fields are kept
(``extra="allow"``): a schema surprise degrades the display, it never
raises at parse time. Callers in normalize.py treat every attribute as
possibly None.

Model names mirror the payload nesting.
"""

from pydantic import BaseModel, ConfigDict


class _TolerantModel(BaseModel):
    model_config = ConfigDict(extra="allow")


# --- Livestats window feed (feed.lolesports.com/livestats/v1/window) ---


class ParticipantMetadata(_TolerantModel):
    """Static per-player info. championId arrives as a name string
    (e.g. "Olaf"), not a numeric id — verified against fixtures."""

    participantId: int | None = None
    esportsPlayerId: str | None = None
    summonerName: str | None = None
    championId: str | None = None
    role: str | None = None


class TeamMetadata(_TolerantModel):
    esportsTeamId: str | None = None
    participantMetadata: list[ParticipantMetadata] | None = None


class WindowGameMetadata(_TolerantModel):
    patchVersion: str | None = None
    blueTeamMetadata: TeamMetadata | None = None
    redTeamMetadata: TeamMetadata | None = None


class WindowParticipant(_TolerantModel):
    """One per-player snapshot inside an inner frame. The feed carries no
    item data, so there is no items field here by design, not by omission."""

    participantId: int | None = None
    totalGold: int | None = None
    level: int | None = None
    kills: int | None = None
    deaths: int | None = None
    assists: int | None = None
    creepScore: int | None = None
    currentHealth: int | None = None
    maxHealth: int | None = None


class WindowTeam(_TolerantModel):
    """One side's snapshot. dragons is the cumulative list of elements
    taken (e.g. ["ocean"]); an empty list means none taken."""

    totalGold: int | None = None
    inhibitors: int | None = None
    towers: int | None = None
    barons: int | None = None
    totalKills: int | None = None
    dragons: list[str] | None = None
    participants: list[WindowParticipant] | None = None


class WindowInnerFrame(_TolerantModel):
    """One sub-frame. rfc460Timestamp is a wall-clock capture time, not a
    game clock — there is no game-clock field in the feed."""

    rfc460Timestamp: str | None = None
    gameState: str | None = None
    blueTeam: WindowTeam | None = None
    redTeam: WindowTeam | None = None


class WindowFrame(_TolerantModel):
    """One raw window response: metadata plus ~10s of inner frames."""

    esportsGameId: str | None = None
    esportsMatchId: str | None = None
    frames: list[WindowInnerFrame] | None = None
    gameMetadata: WindowGameMetadata | None = None


# --- Event details / getLive (esports-api.lolesports.com/persisted/gw) ---


class MatchResult(_TolerantModel):
    outcome: str | None = None
    gameWins: int | None = None


class MatchTeamEntry(_TolerantModel):
    """A team in a match or game block. Per-game entries carry only
    ``id`` and ``side`` ("blue"/"red"); match-level entries carry the
    display fields and ``result``."""

    id: str | None = None
    name: str | None = None
    code: str | None = None
    image: str | None = None
    slug: str | None = None
    result: MatchResult | None = None
    record: dict[str, int] | None = None
    side: str | None = None


class GameEntry(_TolerantModel):
    number: int | None = None
    id: str | None = None
    state: str | None = None
    teams: list[MatchTeamEntry] | None = None
    vods: list[dict[str, object]] | None = None


class Strategy(_TolerantModel):
    type: str | None = None
    count: int | None = None


class MatchInfo(_TolerantModel):
    strategy: Strategy | None = None
    teams: list[MatchTeamEntry] | None = None
    games: list[GameEntry] | None = None


class LeagueInfo(_TolerantModel):
    id: str | None = None
    slug: str | None = None
    name: str | None = None
    image: str | None = None


class EventInfo(_TolerantModel):
    id: str | None = None
    type: str | None = None
    league: LeagueInfo | None = None
    match: MatchInfo | None = None


class EventData(_TolerantModel):
    event: EventInfo | None = None


class EventDetails(_TolerantModel):
    """Raw getEventDetails response."""

    data: EventData | None = None


class LiveEvent(EventInfo):
    """One entry in getLive's schedule.events. Same shape as an event
    block, plus live-listing fields."""

    startTime: str | None = None
    state: str | None = None
    blockName: str | None = None


class LiveSchedule(_TolerantModel):
    events: list[LiveEvent] | None = None


class LiveData(_TolerantModel):
    schedule: LiveSchedule | None = None


class GetLive(_TolerantModel):
    """Raw getLive response."""

    data: LiveData | None = None
