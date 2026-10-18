# TASKS.md — Synthetic Revenue Dataset Generator

Project path: `data/` (this project only; reference sample is `data/sample/`).

## 0. Setup & dependencies
- [x] Confirm Python available with `pandas`, `pyarrow`, `pyyaml` installed.
- [x] Create `data/pyproject.toml` or `data/requirements.txt` scoped to this
  generator (do not edit root `pyproject.toml`).
- [x] Ensure the generator runs under `uv` (e.g. `uv run --project data python data/generate.py --config data/config.yaml`).
- [x] Refactor generator into modules: `config.py`, `timeline.py`, `dimensions.py`, `transactions.py`, `gl_fx.py`, `defects.py`, `manifest.py`, `output.py` (entry point stays `generate.py`).
- [x] Create `data/TASKS.md` (this file) and keep updated.

## 1. Configuration (`data/config.py`)
- [x] Create `data/config.yaml` with clarified structure (base_customers,
  growth_adds_per_month, currencies, gl_accounts, item_categories).
- [x] Validate all keys present and no hardcoded overrides.
- [x] Create `data/schema/` directory.

## 2. Timeline logic (in `data/timeline.py`)
- [x] Parse `start_month` into year/month.
- [x] Generate list of `n_months` period strings (`YYYY-MM`).
- [x] Assign each month to a phase based on cumulative phase months.
- [x] Implement seasonal multiplier function by calendar month.
- [x] Implement growth volume formula.
- [x] Implement plateau volume formula.
- [x] Implement decline volume formula.
- [x] Implement monthly order-count list (rounded ints).
- [x] Implement active-customer tracking helpers (open/churn month).
- [x] Add docstrings and type hints.

## 3. Schema reference files (`data/schema/*.yaml`)
- [x] Confirm schemas programmatically from `data/sample/*.parquet` and
  `data/sample/data_dictionary.md`.
- [x] Write generated reference files (no hand-authored column lists).

## 4. Dimension generation (`data/dimensions.py`)
- [x] Load and strictly validate config (raise on missing key).
- [x] Initialize single seeded RNG (`np.random.default_rng(seed)`).
- [x] Generate `manufacturers` (`scale.manufacturers` rows).
- [x] Generate `distribution_centers` (`scale.distribution_centers` rows).
- [x] Generate `items` (`scale.items` rows) with drift hooks.
- [x] Generate base customers (`scale.base_customers` rows) at month 1.
- [x] Generate growth-phase customer adds (`scale.growth_adds_per_month`).
- [x] Assign churn months for decline phase.
- [x] Snapshot dimension attributes at generation time.
- [x] Add `customers.currency` (ISO-4217) for FX gap support.

## 5. Transactional generation - clean months (`data/transactions.py`)
- [x] Global ID counters for all tables.
- [x] Monthly order header generation (vectorized).
- [x] Monthly order line generation (1-4 lines per order).
- [x] Enforce `(order_id, item_id)` uniqueness.
- [x] Generate shipments per order.
- [x] Generate shipment_lines linked to order_line_id.
- [x] Handle month-end spillover for ship dates.
- [x] Generate invoices per order.
- [x] Generate invoice_lines per order line.
- [x] Handle month-end spillover for invoice dates.
- [x] Generate ar_ledger (1:1 with invoices).
- [x] Generate backorders for under-shipped lines.
- [x] Generate returns (sampled lines).
- [x] Ensure clean months (1-6) have zero defects (defects not yet implemented).

## 6. GL and FX tables (`data/gl_fx.py`)
- [x] Generate `gl_revenue` at `(period, account_id, item_category)` grain
  with nullable `customer_id` (top-N only); rows derived from
  `scale.gl_accounts × scale.item_categories` (sampled).
- [x] Set recognized revenue from billings baseline.
- [x] Generate `fx_rates` (`scale.currencies × n_months`).
- [x] Add load_date and version columns.

## 7. Defect injection (in `data/defects.py`)
- [x] Implement defect logging helper with exact required fields.
- [x] Implement `orphaned_item_id`.
- [x] Implement `duplicate_invoice_line`.
- [x] Implement `missing_customer_mapping`.
- [x] Implement `stale_load`.
- [x] Implement `billings_gl_variance`.
- [x] Implement `restatement`.
- [x] Implement `fx_gap`.
- [x] Implement `orphaned_backorder`.
- [x] Implement `phantom_return`.
- [x] Distribute defects across months ≥ enabled_from_month.
- [x] Concentrate defects at month-end/handoff days.
- [x] Ensure each `row_key` points to a real row.

## 8. Manifest (in `data/manifest.py`)
- [x] Assemble manifest with required fields.
- [x] Compute SHA-256 per parquet file.
- [x] Compute size_bytes per file.
- [x] Count defects by type.
- [x] Write ISO `generated_at` timestamp.

## 9. Output writing (`data/output.py`)
- [x] Create `data/runs/<name>/` directory.
- [x] Write all 15 Parquet tables (sorted, index=False) with all months.
- [x] Write `defects.json`.
- [x] Write `manifest.json`.
- [x] Ensure output < 2 GB.

## 10. README (`data/README.md`)
- [x] How to run section.
- [x] New scenario creation section.
- [x] Verification queries section.
- [x] Scenario examples (baseline_run, severe_decline, churn_spike).

## 11. Verification & reproducibility
- [x] Run `python data/generate.py --config data/config.yaml`.
- [x] Confirm all 15 tables + defects.json + manifest.json exist.
- [x] Confirm months 1–6 have zero defects.
- [x] Confirm months 7+ defect count meets minimum.
- [x] Confirm `ar_ledger` rows == `invoices` rows.
- [x] Confirm all defect `row_key` values resolve.
- [x] Rerun and compare Parquet hashes (byte-identical).
- [x] Compare manifests (identical except `generated_at`).
- [x] Test seed change produces different data, same defect counts.
- [x] Test phase change produces different volume arc.
- [x] Check total size < 2 GB.
- [x] Check total Python LOC < 1,500.

## 12. Final cleanup
- [x] Remove temporary files.
- [x] Final review of diff.
- [x] Commit if applicable.
