"""Seed historical FP&A discussion messages for dashboard chart threads.

The messages span the synthetic data window (2021-10 through 2026-09) so the
Scenarios date filters can be exercised against realistic history. The script
is idempotent per anchor: if an anchor already has messages, it is left alone.

Usage::

    python -m backend.db.seed_threads
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from backend.db.connection import close_pool, get_connection, init_pool

ANCHORS = (
    "chart-revenue-plan",
    "chart-variance-category",
    "chart-growth",
    "chart-attainment",
)

TITLES = {
    "chart-revenue-plan": "Revenue, Billings & Plan discussion",
    "chart-variance-category": "Variance by Category discussion",
    "chart-growth": "Month-over-Month Growth discussion",
    "chart-attainment": "Target Attainment discussion",
}

CONTENT = {
    "chart-revenue-plan": [
        "Revenue in Q4 2021 is tracking 5% below plan. We need to investigate whether this is a data gap or a true miss.",
        "I checked the Billings vs GL variance for 2022. It is within tolerance, but the trend is widening.",
        "The latest load shows a soft month. Let's separate FX movement from underlying volume before we react.",
        "Q3 2024 revenue is up sequentially but still under target. Worth a deeper review of the enterprise category mix.",
        "December 2025 close looks clean. The remaining gap is concentrated in two enterprise accounts.",
        "Revenue is now tracking close to plan. I would like the driver mix before we revise the forecast.",
    ],
    "chart-variance-category": [
        "Category variance widened in 2022. Industrial is the main contributor.",
        "Billings vs GL for 2023 is within tolerance, but the direction is not improving.",
        "Can we confirm the 2024 restatement was loaded? Variance looks artificially low.",
        "Office and Safety flipped sign this quarter. Let's inspect the category mapping drift.",
        "Variance is back inside tolerance for 2025, mainly due to the Q4 true-up. Latest month nets small, but one category is offsetting another.",
    ],
    "chart-growth": [
        "MoM growth turned negative in early 2023. Is seasonality explaining all of it?",
        "Growth has decelerated for the third straight month. I would like a volume-versus-price split.",
        "The 2024 rebound looks real in SMB but not in enterprise.",
        "Q1 2025 growth is flat. Let's check whether returns are masking the underlying trend.",
        "Growth improved in late 2025, but the base is weaker. Latest MoM is positive again, so it is time to revisit the scenario assumptions.",
    ],
    "chart-attainment": [
        "Target attainment is 92% for 2022. Still healthy, but the buffer is shrinking.",
        "Attainment dropped below 90% in 2023. Let's discuss in the next sync.",
        "2024 is tracking at 87% of plan. The miss is concentrated in Q3.",
        "Attainment recovered to 89% in 2025, but the trend is still below target.",
        "Latest month attainment is 85%. We need to decide whether to re-plan or investigate the data before the review.",
    ],
}


def _quarterly_dates() -> list[date]:
    """Quarterly checkpoints from 2021-10 through 2026-09."""
    dates: list[date] = []
    year, month = 2021, 10
    while (year, month) <= (2026, 7):
        dates.append(date(year, month, 15))
        month += 3
        if month > 12:
            month -= 12
            year += 1
    dates.append(date(2026, 9, 15))
    return dates


def seed_threads() -> dict[str, int]:
    """Insert one realistic discussion message per quarterly checkpoint."""
    dates = _quarterly_dates()
    counts = {anchor: 0 for anchor in ANCHORS}
    should_seed = {anchor: False for anchor in ANCHORS}
    inserted = 0

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT persona_id FROM personas WHERE persona_id IN ('analyst', 'manager')"
            )
            available = {row[0] for row in cur.fetchall()}
            missing = {"analyst", "manager"} - available
            if missing:
                raise RuntimeError(
                    "Missing personas: " + ", ".join(sorted(missing))
                    + ". Boot the app or run backend.db.seed first."
                )

            for anchor in ANCHORS:
                cur.execute(
                    """
                    INSERT INTO discussions (anchor_type, anchor_id, title)
                    VALUES ('analysis', %s, %s)
                    ON CONFLICT (anchor_type, anchor_id)
                    DO UPDATE SET title = EXCLUDED.title
                    RETURNING discussion_id
                    """,
                    (anchor, TITLES[anchor]),
                )
                discussion_id = cur.fetchone()[0]
                cur.execute(
                    "SELECT COUNT(*) FROM messages WHERE discussion_id = %s",
                    (discussion_id,),
                )
                if cur.fetchone()[0] > 0:
                    continue
                should_seed[anchor] = True

            for index, day in enumerate(dates):
                anchor = ANCHORS[index % len(ANCHORS)]
                if not should_seed[anchor]:
                    continue
                message_index = index // len(ANCHORS)
                persona_id = "analyst" if index % 2 == 0 else "manager"
                created_at = datetime(
                    day.year, day.month, day.day, 9, 30, tzinfo=timezone.utc
                )
                cur.execute(
                    """
                    INSERT INTO messages
                        (discussion_id, persona_id, content, created_at)
                    SELECT discussion_id, %s, %s, %s
                    FROM discussions
                    WHERE anchor_type = 'analysis' AND anchor_id = %s
                    """,
                    (
                        persona_id,
                        CONTENT[anchor][message_index % len(CONTENT[anchor])],
                        created_at,
                        anchor,
                    ),
                )
                inserted += 1
                counts[anchor] += 1

        conn.commit()

    return {"inserted": inserted, "by_anchor": counts}


def main() -> int:
    init_pool()
    try:
        summary = seed_threads()
    finally:
        close_pool()
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
