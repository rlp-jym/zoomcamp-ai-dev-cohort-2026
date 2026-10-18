# AGENTS.md — Synthetic Revenue Dataset Generator (data/)

This file lives at `data/AGENTS.md`. Invoke the coding agent from `data/`
so this file is discovered, or symlink to root.

Scope: everything under `data/` only. Do not touch files outside `data/`.

## Purpose
Generate a config-driven, seeded, reproducible synthetic revenue dataset
(15 Parquet tables + defects.json + manifest.json) used as test fixtures
for a later Revenue Data Reliability Platform.

## Hard constraints
- Single entry point: `python data/generate.py --config data/config.yaml`.
- Run under `uv` when available: `uv run --project data python data/generate.py --config data/config.yaml`.
- Output directory: `data/runs/<config.name>/`.
- Each run produces **15 Parquet files**, one per table. Each file contains
  **all months** of rows for that table (distinguished by date columns such
  as `order_date`, `invoice_date`, `period`).
- Flat layout only:
  ```
  data/runs/<name>/
  ├── orders.parquet
  ├── order_lines.parquet
  ├── shipments.parquet
  ├── shipment_lines.parquet
  ├── invoices.parquet
  ├── invoice_lines.parquet
  ├── ar_ledger.parquet
  ├── returns.parquet
  ├── backorders.parquet
  ├── customers.parquet
  ├── items.parquet
  ├── distribution_centers.parquet
  ├── manufacturers.parquet
  ├── gl_revenue.parquet
  ├── fx_rates.parquet
  ├── defects.json
  └── manifest.json
  ```
- Exactly 16 tables: 13 from `data/SOURCES.md` + `gl_revenue` + `fx_rates` + `budget`.
  `budget` is reference-only (no defects, no validation). No other tables.
- Column names, types, nullability, FKs must match
  `data/sample/data_dictionary.md` and `data/sample/*.parquet` for the 13
  source tables.
- All config values read from config; no hardcoded parameters from the
  listed config.
- Single seeded RNG per run; same seed + config = byte-identical output.
- Pure functions where possible; pass seeded RNG explicitly; no global state.
- No silent fallbacks — missing config key must fail loudly.
- Target < 1,500 lines of Python total.
- Do not use the reference sample's actual data, numbers, seed, or license.
  Structure only.

## Module responsibilities
- `data/generate.py` — all logic in one file. Optional split into
  `data/timeline.py` and `data/defects.py` only if `generate.py` exceeds
  ~1,500 lines. No `data/manifest.py`; fold manifest assembly into
  `generate.py`.

## Schema source
For the 13 source tables in `data/SOURCES.md`, read schema directly from:
- `data/sample/*.parquet` (types)
- `data/sample/data_dictionary.md` (names, nullability, FKs)

Do not hand-write column lists for these tables in `schema/*.yaml` beyond
confirming them programmatically. The `schema/` directory holds generated
schema reference files, not a hand-authored second source of truth. If a
column exists in the sample dictionary, replicate it exactly.

## Deviations from the sample — only three
1. `customers.currency` — new column, ISO-4217 string. Required for the
   `fx_gap` defect. Deliberate deviation.
2. `gl_revenue` — new table. Grain `(period, account_id, item_category)`,
   with `customer_id` nullable and populated only for top-N customers.
   Columns `recognized_revenue_amt`, `load_date`, `version`. Expect
   hundreds to thousands of rows per period, not 2.
3. `fx_rates` — new table. Grain `(currency, period)`. Column
   `rate_to_usd`.

Everything else must match the sample schema.

## config.yaml — clarified keys
- `scale.base_customers` — customers present at month 1.
- `scale.growth_adds_per_month` — net new customers per month during growth.
- `scale.currencies` — number of currencies in `fx_rates`.
- `scale.gl_accounts` and `scale.item_categories` — derive `gl_revenue`
  row count; not hardcoded.

## Quality gates
- Months 1–6: zero defect entries.
- Months ≥ enabled_from_month: ≥ `counts_per_type_per_month × n_months ×
  n_enabled_types` entries.
- `ar_ledger` row count == `invoices` row count.
- All structural invariants hold in clean months.
- Rerun produces byte-identical Parquet and identical manifest except
  `generated_at`.
- Total dataset size < 2 GB.

## Editing rules
- `data/sample/` is read-only reference. Do not modify, regenerate, or
  rewrite any file under `data/sample/`.
- Keep changes minimal and consistent with existing style.
- Update `data/TASKS.md` checkboxes as work completes.
- Never commit generated `data/runs/` or `data/sample/` artifacts.
