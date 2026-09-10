"""Tests for the Riot HTTP client.

Uses httpx.MockTransport: the real client runs, only HTTP is stubbed.
Payloads are deliberately opaque — no Riot field names appear here, because
parsing is deferred until recorded fixtures exist. URL assertions use the
request path only, so no live Riot hostname appears in this file.

Each call returns a FetchResult: data is the raw JSON object (None when
there is nothing to report), ok is False only when the fetch itself
failed. HTTP 204 is ok-without-data, never an error.
"""

import logging
import re
from collections.abc import Callable
from datetime import datetime, timezone

import httpx
import pytest

from nexus.riot.client import FetchResult, RiotClient, aligned_starting_time


def _transport(
    handler: Callable[[httpx.Request], httpx.Response],
) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def _ok(payload: object) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    return _transport(handler)


async def test_get_live_happy_path_returns_payload_verbatim() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["key"] = request.headers["x-api-key"]
        seen["hl"] = str(request.url.params["hl"])
        return httpx.Response(200, json={"ok": True, "items": [1, 2]})

    client = RiotClient(api_key="secret", transport=_transport(handler))
    try:
        result = await client.get_live()
        assert result == FetchResult(data={"ok": True, "items": [1, 2]}, ok=True)
    finally:
        await client.aclose()
    assert seen["path"] == "/persisted/gw/getLive"
    assert seen["key"] == "secret"
    assert seen["hl"] == "en-US"


async def test_missing_fields_tolerated() -> None:
    client = RiotClient(api_key="secret", transport=_ok({}))
    try:
        assert await client.get_live() == FetchResult(data={}, ok=True)
    finally:
        await client.aclose()


async def test_non_object_json_is_a_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = RiotClient(api_key="secret", transport=_ok([1, 2, 3]))
    try:
        with caplog.at_level(logging.WARNING, logger="nexus.riot.client"):
            assert await client.get_live() == FetchResult(data=None, ok=False)
    finally:
        await client.aclose()
    assert caplog.records, "expected a warning for non-object JSON"


async def test_204_is_ok_without_data_silently(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(204)

    client = RiotClient(api_key="secret", transport=_transport(handler))
    try:
        with caplog.at_level(logging.WARNING, logger="nexus.riot.client"):
            assert await client.get_live() == FetchResult(data=None, ok=True)
            assert await client.get_event_details("m1") == FetchResult(
                data=None, ok=True
            )
            assert await client.get_window(
                "g1", "2026-01-01T00:00:00.000Z"
            ) == FetchResult(data=None, ok=True)
    finally:
        await client.aclose()
    assert caplog.records == []


async def test_403_is_a_failure_and_warns_about_rotation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "forbidden"})

    client = RiotClient(api_key="secret", transport=_transport(handler))
    try:
        with caplog.at_level(logging.WARNING, logger="nexus.riot.client"):
            result = await client.get_live()
            assert result == FetchResult(data=None, ok=False)
    finally:
        await client.aclose()
    assert any("rotat" in record.message.lower() for record in caplog.records)


async def test_500_is_a_failure_and_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"message": "boom"})

    client = RiotClient(api_key="secret", transport=_transport(handler))
    try:
        with caplog.at_level(logging.WARNING, logger="nexus.riot.client"):
            result = await client.get_event_details("m1")
            assert result == FetchResult(data=None, ok=False)
    finally:
        await client.aclose()
    assert caplog.records, "expected a warning for HTTP 500"


async def test_timeout_is_a_failure_and_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("connection timed out", request=request)

    client = RiotClient(api_key="secret", transport=_transport(handler))
    try:
        with caplog.at_level(logging.WARNING, logger="nexus.riot.client"):
            result = await client.get_window("g1", "2026-01-01T00:00:00.000Z")
            assert result == FetchResult(data=None, ok=False)
    finally:
        await client.aclose()
    assert caplog.records, "expected a warning for timeout"


async def test_malformed_json_is_a_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"this is not json")

    client = RiotClient(api_key="secret", transport=_transport(handler))
    try:
        assert await client.get_live() == FetchResult(data=None, ok=False)
    finally:
        await client.aclose()


async def test_api_key_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={})

    client = RiotClient(api_key="super-secret-value", transport=_transport(handler))
    try:
        with caplog.at_level(logging.WARNING, logger="nexus.riot.client"):
            result = await client.get_live()
            assert result.ok is False
    finally:
        await client.aclose()
    assert "super-secret-value" not in caplog.text


async def test_explicit_10s_timeout_configured() -> None:
    client = RiotClient(api_key="secret", transport=_ok({}))
    try:
        timeout = client.http.timeout
        assert timeout.connect == 10.0
        assert timeout.read == 10.0
        assert timeout.write == 10.0
        assert timeout.pool == 10.0
    finally:
        await client.aclose()


async def test_get_event_details_sends_match_id() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["id"] = str(request.url.params["id"])
        return httpx.Response(200, json={"echo": True})

    client = RiotClient(api_key="secret", transport=_transport(handler))
    try:
        result = await client.get_event_details("match-42")
        assert result == FetchResult(data={"echo": True}, ok=True)
    finally:
        await client.aclose()
    assert seen["path"] == "/persisted/gw/getEventDetails"
    assert seen["id"] == "match-42"


async def test_get_window_sends_game_id_and_starting_time() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["starting_time"] = str(request.url.params["startingTime"])
        return httpx.Response(200, json={"frames": []})

    client = RiotClient(api_key="secret", transport=_transport(handler))
    try:
        result = await client.get_window("game-7", "2026-05-01T12:00:00.000Z")
        assert result == FetchResult(data={"frames": []}, ok=True)
    finally:
        await client.aclose()
    assert seen["path"] == "/livestats/v1/window/game-7"
    assert seen["starting_time"] == "2026-05-01T12:00:00.000Z"


def _dt(second: int) -> datetime:
    return datetime(2026, 5, 1, 12, 34, second, 987654, tzinfo=timezone.utc)  # noqa: UP017 - matches src spelling


def test_aligned_starting_time_boundaries() -> None:
    assert aligned_starting_time(_dt(0)) == "2026-05-01T12:34:00.000Z"
    assert aligned_starting_time(_dt(9)) == "2026-05-01T12:34:00.000Z"
    assert aligned_starting_time(_dt(10)) == "2026-05-01T12:34:10.000Z"
    assert aligned_starting_time(_dt(59)) == "2026-05-01T12:34:50.000Z"


def test_aligned_starting_time_defaults_to_now() -> None:
    assert re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d0\.000Z", aligned_starting_time()
    )
