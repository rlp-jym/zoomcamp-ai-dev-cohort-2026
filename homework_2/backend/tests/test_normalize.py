"""Tests for the deferred normalize skeletons.

Steps 4–5 of the build order (recorded fixtures, then real parsing) have
not happened yet, so these functions must exist with exact signatures but
refuse to run. These tests pin that contract.
"""

from datetime import datetime, timezone

import pytest

from nexus.riot import normalize


def test_normalize_window_is_deferred() -> None:
    now = datetime.now(timezone.utc)  # noqa: UP017 - matches src spelling
    with pytest.raises(NotImplementedError):
        normalize.normalize_window({"anything": True}, now=now)


def test_diff_frames_is_deferred() -> None:
    with pytest.raises(NotImplementedError):
        normalize.diff_frames(None, {"anything": True})


def test_normalize_event_details_is_deferred() -> None:
    with pytest.raises(NotImplementedError):
        normalize.normalize_event_details({"anything": True})
