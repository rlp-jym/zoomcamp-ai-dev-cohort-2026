"""Dashboard asset loading.

The frontend is built by Node from ``frontend/`` into ``frontend/dist``. When a
build exists it is served; otherwise the starter's ``dashboard.html`` covers
local development that has not run the frontend build.
"""

from pathlib import Path
from functools import lru_cache

FRONTEND_DIST = Path(__file__).with_name("frontend") / "dist"


@lru_cache(maxsize=1)
def dashboard_html() -> str:
    built = FRONTEND_DIST / "index.html"
    if built.is_file():
        return built.read_text(encoding="utf-8")
    return Path(__file__).with_name("dashboard.html").read_text(encoding="utf-8")


__all__ = ["dashboard_html"]
