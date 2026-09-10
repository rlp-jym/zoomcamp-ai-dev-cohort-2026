"""Tests for the in-memory state store (atomic swap)."""

import threading

from nexus.state import AppState, idle_state


def test_initial_state_is_idle_shaped() -> None:
    store = AppState()
    snapshot = store.get()
    assert snapshot["status"] == "idle"
    assert snapshot["stale"] is False
    assert snapshot["match"] is None
    assert snapshot["game"] is None
    assert set(snapshot) == {"status", "stale", "lastUpdated", "match", "game"}
    assert isinstance(snapshot["lastUpdated"], str)


def test_swap_replaces_state_atomically() -> None:
    store = AppState()
    before = store.get()
    updated = idle_state()
    updated["stale"] = True
    store.swap(updated)
    assert store.get() is updated
    assert store.get() is not before


def test_failed_poll_keeps_last_state() -> None:
    # Simulates the §4 error path: on failure the poller simply never swaps.
    store = AppState()
    keep = store.get()
    assert store.get() is keep


def test_concurrent_read_during_write_never_tears() -> None:
    store = AppState()
    initial = store.get()
    versions = [idle_state() for _ in range(50)]
    valid_ids = {id(initial)} | {id(version) for version in versions}
    seen: list[int] = []
    stop = threading.Event()

    def reader() -> None:
        while not stop.is_set():
            snapshot = store.get()
            assert set(snapshot) == {
                "status",
                "stale",
                "lastUpdated",
                "match",
                "game",
            }
            seen.append(id(snapshot))

    threads = [threading.Thread(target=reader) for _ in range(4)]
    for thread in threads:
        thread.start()
    try:
        for version in versions:
            store.swap(version)
    finally:
        stop.set()
        for thread in threads:
            thread.join()

    assert store.get() is versions[-1]
    assert seen, "reader threads observed no states"
    # Every observed snapshot must be a complete object we wrote, never torn.
    assert set(seen) <= valid_ids
