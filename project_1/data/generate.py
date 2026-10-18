"""Synthetic Revenue Dataset Generator.

Single entry point:
    python data/generate.py --config data/config.yaml
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yaml


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
REQUIRED_KEYS = [
    "name", "seed", "timeline", "scale", "dimension_drift", "defects",
    "reconciliation", "output",
]


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if not isinstance(cfg, dict):
        raise ValueError("config must be a mapping")
    for k in REQUIRED_KEYS:
        if k not in cfg:
            raise ValueError(f"missing config key: {k}")
    return cfg


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------
def _parse_ym(s: str) -> tuple[int, int]:
    y, m = s.split("-")
    return int(y), int(m)


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
    """Return (phase, start_index, end_index_exclusive)."""
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
    months = month_list(tl["start_month"], int(tl["n_months"]))
    # decline start index
    decline_start = None
    for p, start, end in _phase_boundaries(phases):
        if p["name"] == "decline" or p.get("driver") == "churn":
            decline_start = start
            break
    counts = []
    for i, period in enumerate(months):
        phase = phase_for_month(i, phases)
        seasonal = _seasonal_multiplier(period, seasonality)
        driver = phase.get("driver", "none")
        name = phase["name"]
        if name == "growth":
            val = base * (1 + 0.02 * i) * seasonal
        elif name == "plateau":
            val = base * 1.28 * seasonal
        elif name == "decline":
            di = i - (decline_start if decline_start is not None else i)
            val = base * 1.28 * (1 - 0.015 * di) * seasonal
        else:
            val = base * seasonal
        counts.append(int(round(val)))
    return counts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    cfg = load_config(args.config)
    counts = monthly_order_counts(cfg)
    print(f"months={len(counts)} total_orders={sum(counts)} first={counts[0]} last={counts[-1]}")


if __name__ == "__main__":
    main()