"""Tests for the five API endpoints against openapi.yaml.

Uses a stub poller so lifespan runs without network. State assertions check
that nullable keys are present-with-null, never omitted.
"""

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from nexus.main import create_app
from nexus.state import AppState, idle_state
from nexus.storage.json_file import JsonFilePreferencesRepository

LIVE_STATE: dict[str, Any] = {
    "status": "live",
    "stale": False,
    "lastUpdated": "2026-09-10T12:34:56Z",
    "match": {
        "id": "m1",
        "bestOf": 3,
        "gameNumber": 2,
        "nextGameNumber": None,
        "seriesScore": {"home": 1, "away": 0},
        "teams": {
            "home": {
                "name": "T1",
                "code": "T1",
                "logo": None,
                "color": "#E2012D",
            },
            "away": {
                "name": "Gen.G",
                "code": "GEN",
                "logo": None,
                "color": "#AA8B56",
            },
        },
    },
    "game": {
        "clockSeconds": 1247,
        "kills": {"home": 7, "away": 4},
        "gold": {"home": 42100, "away": 39800},
        "towers": {"home": 3, "away": 2},
        "dragons": {"home": ["infernal", "ocean"], "away": None},
        "barons": {"home": 0, "away": 1},
        "players": {
            "home": [
                {
                    "role": "TOP",
                    "champion": None,
                    "kills": 2,
                    "deaths": 1,
                    "assists": 3,
                    "cs": 210,
                    "items": [1234, 5678],
                }
            ],
            "away": [],
        },
        "objectiveTimers": {"dragon": 45, "baron": None},
    },
}


class StubPoller:
    """Stand-in for the real poller: proves lifespan starts it, does no I/O."""

    def __init__(self) -> None:
        self.started = False

    async def run(self) -> None:
        self.started = True


def _client(tmp_path: Path, poller: StubPoller | None = None) -> TestClient:
    store = AppState()
    repo = JsonFilePreferencesRepository(tmp_path / "prefs.json")
    app = create_app(store=store, repo=repo, poller=poller or StubPoller())
    return TestClient(app)


def test_get_state_idle_shape(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.get("/api/state")
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"status", "stale", "lastUpdated", "match", "game"}
    assert body["status"] == "idle"
    assert body["stale"] is False
    assert "match" in body and body["match"] is None
    assert "game" in body and body["game"] is None


def test_get_state_serves_live_shape_verbatim(tmp_path: Path) -> None:
    store = AppState()
    store.swap(LIVE_STATE)
    repo = JsonFilePreferencesRepository(tmp_path / "prefs.json")
    app = create_app(store=store, repo=repo, poller=StubPoller())
    with TestClient(app) as client:
        response = client.get("/api/state")
    assert response.status_code == 200
    assert response.json() == LIVE_STATE


def test_get_live_matches_is_empty_list(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.get("/api/matches/live")
    assert response.status_code == 200
    assert response.json() == []


def test_preferences_round_trip_with_defaults(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        initial = client.get("/api/preferences")
        assert initial.status_code == 200
        assert initial.json() == {"pinned_match_id": None, "view_mode": "standard"}

        updated = client.put(
            "/api/preferences",
            json={"pinned_match_id": "m1", "view_mode": "deep"},
        )
        assert updated.status_code == 200
        assert updated.json() == {"pinned_match_id": "m1", "view_mode": "deep"}

        reread = client.get("/api/preferences")
        assert reread.json() == {"pinned_match_id": "m1", "view_mode": "deep"}


def test_preferences_reject_bad_view_mode(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.put(
            "/api/preferences",
            json={"pinned_match_id": None, "view_mode": "ultra"},
        )
    assert response.status_code == 422


def test_selection_pin_and_unpin(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        pinned = client.put("/api/selection", json={"matchId": "match-9"})
        assert pinned.status_code == 200
        assert pinned.json() == {"pinned_match_id": "match-9", "view_mode": "standard"}

        stored = client.get("/api/preferences")
        assert stored.json()["pinned_match_id"] == "match-9"

        unpinned = client.put("/api/selection", json={"matchId": None})
        assert unpinned.status_code == 200
        assert unpinned.json()["pinned_match_id"] is None


def test_selection_rejects_missing_match_id(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.put("/api/selection", json={})
    assert response.status_code == 422


def test_lifespan_starts_poller(tmp_path: Path) -> None:
    poller = StubPoller()
    with _client(tmp_path, poller):
        pass
    assert poller.started is True


def test_unknown_path_is_404(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        assert client.get("/api/nope").status_code == 404


def test_idle_state_factory_keeps_keys_present() -> None:
    assert set(idle_state()) == {"status", "stale", "lastUpdated", "match", "game"}
