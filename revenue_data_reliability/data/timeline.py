"""Timeline and volume logic for the synthetic revenue dataset."""

from __future__ import annotations

from datetime import date, timedelta


def _parse_ym(s: str) -> tuple[int, int]:
    y, m = s.split("-")
    return int(y), int(m)


def previous_month_end(today: date | None = None) -> date:
    """Last day of the month before *today* (defaults to the current date)."""
    today = today or date.today()
    return date(today.year, today.month, 1) - timedelta(days=1)


def month_span_ending_previous_month(
    n_months: int, today: date | None = None
) -> tuple[str, str]:
    """Return ``(start_month, end_month)`` for *n_months* ending last month."""
    n_months = int(n_months)
    if n_months < 1:
        raise ValueError("n_months must be >= 1")
    end = previous_month_end(today)
    end_index = end.year * 12 + (end.month - 1)
    start_year, start_month0 = divmod(end_index - (n_months - 1), 12)
    return (
        f"{start_year:04d}-{start_month0 + 1:02d}",
        f"{end.year:04d}-{end.month:02d}",
    )


def month_list(start_month: str, n_months: int) -> list[str]:
    y, m = _parse_ym(start_month)
    out = []
    for i in range(n_months):
        mm = m + i
        yy = y + (mm - 1) // 12
        mm = (mm - 1) % 12 + 1
        out.append(f"{yy:04d}-{mm:02d}")
    return out


def _phase_boundaries(phases: list[dict]) -> list[tuple[dict, int, int]]:
    res = []
    cur = 0
    for p in phases:
        start = cur
        cur += int(p["months"])
        res.append((p, start, cur))
    return res


def phase_for_month(month_index: int, phases: list[dict]) -> dict:
    for p, start, end in _phase_boundaries(phases):
        if start <= month_index < end:
            return p
    raise ValueError(f"month_index {month_index} outside phases")


def _seasonal_multiplier(period: str, seasonality: dict) -> float:
    m = int(period.split("-")[1])
    if m == 1:
        return float(seasonality["january_dip_multiplier"])
    if m in (3, 4, 5):
        return float(seasonality["spring_peak_multiplier"])
    if m in (6, 7, 8):
        return float(seasonality["summer_peak_multiplier"])
    if m in (10, 11, 12):
        return float(seasonality["q4_lift_multiplier"])
    return 1.0


def monthly_order_counts(cfg: dict) -> list[int]:
    tl = cfg["timeline"]
    scale = cfg["scale"]
    base = float(scale["orders_per_month_base"])
    phases = tl["phases"]
    seasonality = tl["seasonality"]
    trend = float(tl.get("trend_per_month", 0.0))
    months = month_list(tl["start_month"], int(tl["n_months"]))
    decline_start = None
    for p, start, _end in _phase_boundaries(phases):
        if p["name"] == "decline" or p.get("driver") == "churn":
            decline_start = start
            break
    counts = []
    for i, period in enumerate(months):
        phase = phase_for_month(i, phases)
        seasonal = _seasonal_multiplier(period, seasonality)
        name = phase["name"]
        if name == "growth":
            # trend_per_month drives the actual trajectory: 0 is flat,
            # positive grows, negative declines. Clamped so a long window
            # cannot produce non-positive volumes.
            factor = max(0.2, 1.0 + trend * i)
            val = base * factor * seasonal
        elif name == "plateau":
            val = base * 1.28 * seasonal
        elif name == "decline":
            di = i - (decline_start if decline_start is not None else i)
            val = base * 1.28 * (1 - 0.015 * di) * seasonal
        else:
            val = base * seasonal
        counts.append(int(round(val)))
    return counts


def period_start_date(period: str) -> date:
    y, m = _parse_ym(period)
    return date(y, m, 1)
