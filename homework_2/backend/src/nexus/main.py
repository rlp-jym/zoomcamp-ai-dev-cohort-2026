"""FastAPI application: contract models, routes, lifespan, entry point.

Response shapes mirror openapi.yaml exactly. Nullable fields stay required:
the key is always present and the value may be null.
"""

import asyncio
import json
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal, Protocol, cast

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict

from nexus.config import Settings, load_settings, preferences_path
from nexus.riot.client import RiotClient
from nexus.state import AppState
from nexus.storage.base import PreferencesRepository
from nexus.storage.json_file import JsonFilePreferencesRepository
from nexus.storage.sqlalchemy_repo import (
    Base,
    SqlAlchemyPreferencesRepository,
    default_engine,
    sqlite_file_path,
)

logger = logging.getLogger(__name__)

MISSING_KEY_MESSAGE = (
    "RIOT_API_KEY is not set. Copy backend/.env.example to backend/.env and fill it in."
)


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Team(ContractModel):
    name: str
    code: str
    logo: str | None
    color: str | None


class Player(ContractModel):
    role: str
    champion: str | None
    kills: int | None
    deaths: int | None
    assists: int | None
    cs: int | None
    items: list[int]


class Objectives(ContractModel):
    dragon: int | None
    baron: int | None


class SeriesScore(ContractModel):
    home: int
    away: int


class Teams(ContractModel):
    home: Team
    away: Team


class SideInts(ContractModel):
    home: int | None
    away: int | None


class SideDragons(ContractModel):
    home: list[str] | None
    away: list[str] | None


class SidePlayers(ContractModel):
    home: list[Player]
    away: list[Player]


class Game(ContractModel):
    clockSeconds: int | None
    kills: SideInts
    gold: SideInts
    towers: SideInts
    dragons: SideDragons
    barons: SideInts
    players: SidePlayers
    objectiveTimers: Objectives


class Match(ContractModel):
    id: str
    bestOf: int | None
    gameNumber: int | None
    nextGameNumber: int | None
    seriesScore: SeriesScore
    teams: Teams


class State(ContractModel):
    status: Literal["live", "between_games", "idle"]
    stale: bool
    lastUpdated: str
    match: Match | None
    game: Game | None


class LiveMatch(ContractModel):
    id: str
    bestOf: int | None
    teams: Teams
    league: str | None


class SelectionRequest(ContractModel):
    matchId: str | None


class Preferences(ContractModel):
    pinned_match_id: str | None
    view_mode: Literal["standard", "deep"]


class PollerLike(Protocol):
    """Structural type for the poller; lifespan only needs run()."""

    async def run(self) -> None: ...


def ensure_defaults(repo: PreferencesRepository) -> None:
    """Create the preferences file with defaults when keys are missing."""
    existing = repo.all()
    if "pinned_match_id" not in existing:
        repo.set("pinned_match_id", "null")
    if "view_mode" not in existing:
        repo.set("view_mode", "standard")


def read_preferences(repo: PreferencesRepository) -> Preferences:
    """Read preferences tolerantly; corrupt values fall back to defaults."""
    raw = repo.all()
    try:
        pinned: Any = json.loads(raw.get("pinned_match_id", "null"))
    except json.JSONDecodeError:
        pinned = None
    if pinned is not None and not isinstance(pinned, str):
        pinned = None
    raw_view = raw.get("view_mode", "standard")
    view_mode = cast(
        "Literal['standard', 'deep']",
        raw_view if raw_view in ("standard", "deep") else "standard",
    )
    return Preferences(pinned_match_id=pinned, view_mode=view_mode)


def create_app(
    store: AppState, repo: PreferencesRepository, poller: PollerLike
) -> FastAPI:
    ensure_defaults(repo)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        _ = app
        task = asyncio.create_task(poller.run())
        yield
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    app = FastAPI(title="Nexus API", lifespan=lifespan)

    @app.get("/api/state", response_model=State)
    def get_state() -> dict[str, Any]:
        return store.get()

    @app.get("/api/matches/live", response_model=list[LiveMatch])
    def get_live_matches() -> list[Any]:
        return []

    @app.put("/api/selection", response_model=Preferences)
    def put_selection(selection: SelectionRequest) -> Preferences:
        repo.set("pinned_match_id", json.dumps(selection.matchId))
        return read_preferences(repo)

    @app.get("/api/preferences", response_model=Preferences)
    def get_preferences() -> Preferences:
        return read_preferences(repo)

    @app.put("/api/preferences", response_model=Preferences)
    def put_preferences(prefs: Preferences) -> Preferences:
        repo.set("pinned_match_id", json.dumps(prefs.pinned_match_id))
        repo.set("view_mode", prefs.view_mode)
        return read_preferences(repo)

    return app


def require_api_key(settings: Settings) -> None:
    """Exit(1) with the exact message when RIOT_API_KEY is unset."""
    if not settings.riot_api_key:
        sys.stderr.write(MISSING_KEY_MESSAGE + "\n")
        raise SystemExit(1)


def resolve_replay_file(raw: str) -> Path:
    """Locate the replay file for POLL_SOURCE=replay.

    Relative paths resolve against the working directory first, then the
    repo root, so `REPLAY_FILE=replays/...` works whether the server
    starts from backend/ or the repo root.
    """
    candidate = Path(raw)
    if not candidate.is_absolute():
        repo_root = Path(__file__).resolve().parent.parent.parent.parent
        for base in (Path.cwd(), repo_root):
            hit = base / candidate
            if hit.exists():
                return hit
    if candidate.exists():
        return candidate
    sys.stderr.write(f"REPLAY_FILE not found: {raw}\n")
    raise SystemExit(1)


def load_replay_data(path: Path) -> dict[str, Any]:
    """Read and parse the replay file once at startup (demo mode only)."""
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return data
    except (OSError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"Cannot load REPLAY_FILE {path}: {exc}\n")
        raise SystemExit(1) from exc


def create_repository(settings: Settings) -> PreferencesRepository:
    """Select the preferences adapter from STORAGE_BACKEND."""
    if settings.storage_backend == "json":
        return JsonFilePreferencesRepository(preferences_path())
    if settings.storage_backend == "sqlalchemy":
        engine = default_engine(settings.database_url)
        Base.metadata.create_all(engine)
        resolved = sqlite_file_path(settings.database_url)
        if resolved is not None:
            logger.info("Preferences store: sqlalchemy at %s", resolved)
        else:
            logger.info("Preferences store: sqlalchemy (non-file database URL)")
        return SqlAlchemyPreferencesRepository(engine)
    raise ValueError(
        f"Unsupported STORAGE_BACKEND: {settings.storage_backend}. "
        "Expected 'json' or 'sqlalchemy'."
    )


def run() -> None:
    # Local import: the poller is build-order step 6 and may not exist yet.
    from nexus.poller import Poller

    settings = load_settings()
    if settings.poll_source == "live":
        require_api_key(settings)
    try:
        repo = create_repository(settings)
    except ValueError as exc:
        sys.stderr.write(str(exc) + "\n")
        raise SystemExit(1) from exc
    store = AppState()
    if settings.poll_source == "replay":
        logger.info("Replay mode: no Riot calls will be made")
        replay_path = resolve_replay_file(settings.replay_file)
        poller = Poller(
            client=None,
            store=store,
            settings=settings,
            replay=load_replay_data(replay_path),
        )
    else:
        client = RiotClient(api_key=settings.riot_api_key)
        poller = Poller(
            client=client,
            store=store,
            settings=settings,
            get_pinned=lambda: read_preferences(repo).pinned_match_id,
        )
    app = create_app(store=store, repo=repo, poller=poller)
    uvicorn.run(app, host="127.0.0.1", port=settings.nexus_port)
