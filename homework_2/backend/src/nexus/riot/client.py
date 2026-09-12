"""HTTP client for Riot's public lolesports endpoints.

No parsing happens here: methods return a FetchResult wrapping the raw
JSON object. ``ok`` is False only when the fetch itself failed; HTTP 204
is ok-without-data, never an error. The API key travels in the x-api-key
header and is never written to logs.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 10.0

# The window feed rejects windows ending less than ~20s ago (HTTP 400
# BAD_QUERY_PARAMETER, "ahead of broadcast"). Requesting the current 10s
# boundary lands inside that buffer, so window calls step this far into
# the past first: a 10s window starting at T ends at T+10, and with a 40s
# offset that end is 30-40s old — clear of the buffer with margin left
# for request latency.
ANTI_SPOILER_OFFSET_SECONDS = 40

_LIVE_BASE_URL = "https://esports-api.lolesports.com/persisted/gw"
_FEED_BASE_URL = "https://feed.lolesports.com/livestats/v1"


@dataclass(frozen=True)
class FetchResult:
    """Outcome of one Riot request.

    ``data`` is the raw JSON object, or None when there is nothing to
    report. ``ok`` is False only when the fetch itself failed — HTTP 204
    yields ``FetchResult(data=None, ok=True)``. The poller needs this
    distinction: a 204 counts as success, a failure sets the stale flag.
    """

    data: dict[str, Any] | None
    ok: bool


def aligned_starting_time(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)  # noqa: UP017 - spelling matches root AGENTS.md §6 verbatim
    floored = now.replace(microsecond=0, second=now.second - (now.second % 10))
    return floored.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def window_starting_time(now: datetime | None = None) -> str:
    """startingTime for livestats window calls.

    Same 10s flooring as aligned_starting_time, but offset
    ANTI_SPOILER_OFFSET_SECONDS into the past so the requested window
    ends clear of the feed's ~20s anti-spoiler buffer (specs §7.3 item 5).
    The poller must use this, never the raw aligned time.
    """
    now = now or datetime.now(timezone.utc)  # noqa: UP017 - spelling matches aligned_starting_time
    shifted = now - timedelta(seconds=ANTI_SPOILER_OFFSET_SECONDS)
    return aligned_starting_time(shifted)


class RiotClient:
    """Thin async wrapper around the three lolesports endpoints."""

    def __init__(
        self, api_key: str, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.http = httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(REQUEST_TIMEOUT_SECONDS),
            headers={"x-api-key": api_key},
        )

    async def aclose(self) -> None:
        await self.http.aclose()

    async def get_live(self) -> FetchResult:
        return await self._get(f"{_LIVE_BASE_URL}/getLive", {"hl": "en-US"})

    async def get_event_details(self, match_id: str) -> FetchResult:
        return await self._get(
            f"{_LIVE_BASE_URL}/getEventDetails", {"hl": "en-US", "id": match_id}
        )

    async def get_window(self, game_id: str, starting_time: str) -> FetchResult:
        return await self._get(
            f"{_FEED_BASE_URL}/window/{game_id}", {"startingTime": starting_time}
        )

    async def _get(self, url: str, params: dict[str, str]) -> FetchResult:
        try:
            response = await self.http.get(url, params=params)
        except httpx.HTTPError as exc:
            logger.warning("Riot request failed for %s: %s", url, exc)
            return FetchResult(data=None, ok=False)
        if response.status_code == 204:
            return FetchResult(data=None, ok=True)
        if response.status_code == 403:
            logger.warning(
                "Riot request forbidden for %s; the API key may have rotated", url
            )
            return FetchResult(data=None, ok=False)
        if response.status_code >= 400:
            logger.warning(
                "Riot request failed for %s: HTTP %s", url, response.status_code
            )
            return FetchResult(data=None, ok=False)
        try:
            payload: Any = response.json()
        except ValueError as exc:
            logger.warning("Riot request returned invalid JSON for %s: %s", url, exc)
            return FetchResult(data=None, ok=False)
        if not isinstance(payload, dict):
            logger.warning("Riot request returned non-object JSON for %s", url)
            return FetchResult(data=None, ok=False)
        return FetchResult(data=payload, ok=True)
