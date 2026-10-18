"""Manifest assembly for a generator run."""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def build_manifest(
    cfg: dict,
    out_dir: Path,
    table_names: list[str],
    table_rows: dict[str, int],
    defects: list[dict],
    months: list[str],
) -> dict:
    tables: dict[str, dict] = {}
    for name in table_names:
        p = out_dir / f"{name}.parquet"
        tables[name] = {
            "rows": int(table_rows.get(name, 0)),
            "size_bytes": int(os.path.getsize(p)) if p.exists() else 0,
            "sha256": sha256_file(p) if p.exists() else "",
        }

    defects_by_type: dict[str, int] = {}
    for d in defects:
        defects_by_type[d["type"]] = defects_by_type.get(d["type"], 0) + 1

    return {
        "name": cfg["name"],
        "seed": int(cfg["seed"]),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "month_range": [months[0], months[-1]] if months else [],
        "tables": tables,
        "defects_by_type": defects_by_type,
    }
