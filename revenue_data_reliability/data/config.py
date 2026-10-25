"""Config loading and validation."""

from __future__ import annotations

import yaml

REQUIRED_KEYS = [
    "name", "seed", "timeline", "scale", "dimension_drift", "defects",
    "reconciliation", "output", "concentration", "variance",
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
