"""Raw-payload mapping (DEFERRED until build-order step 5).

No parsing logic may be written here until real Riot responses have been
recorded to tests/fixtures/ (step 4). Writing parsers against guesses is
exactly what the fixture-first build order exists to prevent.
"""

from datetime import datetime
from typing import Any


def normalize_window(raw: dict[str, Any], *, now: datetime) -> dict[str, Any]:
    """Map one raw window frame to the contract-shaped game state."""
    raise NotImplementedError("normalize_window needs recorded fixtures (step 5)")


def diff_frames(
    prev: dict[str, Any] | None, curr: dict[str, Any]
) -> list[dict[str, Any]]:
    """Diff two frames into a list of events."""
    raise NotImplementedError("diff_frames needs recorded fixtures (step 5)")


def normalize_event_details(raw: dict[str, Any]) -> dict[str, Any]:
    """Map raw event details to the contract-shaped match info."""
    raise NotImplementedError(
        "normalize_event_details needs recorded fixtures (step 5)"
    )
