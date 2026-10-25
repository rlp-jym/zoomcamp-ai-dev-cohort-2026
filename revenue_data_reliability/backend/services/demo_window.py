"""Deterministic time window used by validation and reconciliation scans.

The demo scans the latest 12 months of the synthetic dataset (trailing from
the last completed month) instead of the full generated history. Defects are
seeded in every month from ``enabled_from_month`` onward, so the window keeps
rule coverage while reducing the rows DuckDB has to aggregate and spill.

``years_to_backtrack`` still participates in the boundary calculation.  A y1
scenario asks for the same trailing 12 months; a y5 scenario asks for five
years but is capped at the same latest-12-months demo window.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.services.dataset_scale import scale_window

# Number of recent calendar years included in the demo scan.  Keeping this at
# one gives the latest-12-months window the runtime target is based on.
DEMO_WINDOW_YEARS = 1


@dataclass(frozen=True)
class DemoWindow:
    """Inclusive period bounds plus the equivalent half-open date bounds."""

    start_period: str
    end_period: str
    start_date: str
    end_date: str  # Exclusive: first day of the month after ``end_period``.


def demo_window(years_to_backtrack: int | str | None = None) -> DemoWindow:
    """Resolve the deterministic scan window for a scenario.

    The requested history can narrow the demo window (for example, a future
    y1 scenario when the demo window is wider), but it can never widen it.
    """
    demo_start, demo_end = scale_window(DEMO_WINDOW_YEARS)
    start = demo_start

    try:
        requested_years = int(years_to_backtrack) if years_to_backtrack is not None else None
    except (TypeError, ValueError):
        requested_years = None

    if requested_years and requested_years > 0:
        requested_start, _ = scale_window(requested_years)
        start = max(start, requested_start)

    end_year, end_month = (int(part) for part in demo_end.split("-"))
    next_year = end_year + (end_month // 12)
    next_month = (end_month % 12) + 1
    return DemoWindow(
        start_period=start,
        end_period=demo_end,
        start_date=f"{start}-01",
        end_date=f"{next_year:04d}-{next_month:02d}-01",
    )
