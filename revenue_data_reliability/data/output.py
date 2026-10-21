"""Run directory + Parquet/JSON writing."""

from __future__ import annotations

import json
from pathlib import Path

from manifest import build_manifest

TABLE_ORDER = [
    "orders",
    "order_lines",
    "shipments",
    "shipment_lines",
    "invoices",
    "invoice_lines",
    "ar_ledger",
    "returns",
    "backorders",
    "customers",
    "items",
    "distribution_centers",
    "manufacturers",
    "gl_revenue",
    "budget",
    "fx_rates",
]


def write_run(cfg: dict, data: dict, defects: list[dict], months: list[str]) -> Path:
    base = Path(__file__).resolve().parent / "runs" / str(cfg["name"])
    base.mkdir(parents=True, exist_ok=True)

    table_rows: dict[str, int] = {}
    for name in TABLE_ORDER:
        df = data[name]
        if not df.empty and df.columns.size:
            df = df.sort_values(by=df.columns[0]).reset_index(drop=True)
        df.to_parquet(base / f"{name}.parquet", index=False)
        table_rows[name] = int(len(df))

    with open(base / "defects.json", "w", encoding="utf-8") as f:
        json.dump(defects, f, indent=2)

    manifest = build_manifest(cfg, base, TABLE_ORDER, table_rows, defects, months)
    with open(base / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    return base
