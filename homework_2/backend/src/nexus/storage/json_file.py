"""JSON-file preferences repository (file adapter)."""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class JsonFilePreferencesRepository:
    """Persists string preferences to a JSON object file.

    A missing or corrupt file reads as empty; it never raises on read.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def get(self, key: str) -> str | None:
        return self._read().get(key)

    def set(self, key: str, value: str) -> None:
        data = self._read()
        data[key] = value
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(data), encoding="utf-8")

    def all(self) -> dict[str, str]:
        return self._read()

    def _read(self) -> dict[str, str]:
        try:
            raw: Any = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.warning("Ignoring corrupt preferences file %s: %s", self._path, exc)
            return {}
        if not isinstance(raw, dict):
            logger.warning("Ignoring non-object preferences file %s", self._path)
            return {}
        return {str(key): str(value) for key, value in raw.items()}
