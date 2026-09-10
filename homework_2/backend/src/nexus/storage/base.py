"""Preferences repository protocol.

Application code depends on this protocol, never on file I/O directly,
so the backing store can be replaced without a refactor.
"""

from typing import Protocol


class PreferencesRepository(Protocol):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str) -> None: ...
    def all(self) -> dict[str, str]: ...
