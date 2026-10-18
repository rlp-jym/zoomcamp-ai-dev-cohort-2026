# TASKS.md — Synthetic Revenue Dataset Generator

Project path: `data/` (this project only; reference sample is `data/sample/`).

## 0. Setup & dependencies
- [x] Confirm Python available with `pandas`, `pyarrow`, `pyyaml` installed.
- [x] Create `data/pyproject.toml` or `data/requirements.txt` scoped to this
  generator (do not edit root `pyproject.toml`).
- [ ] Ensure the generator runs under `uv` (e.g. `uv run --project data python data/generate.py --config data/config.yaml`).
- [x] Create `data/TASKS.md` (this file) and keep updated.

## 1. Configuration
- [x] Create `data/config.yaml` with clarified structure (base_customers,
  growth_adds_per_month, currencies, gl_accounts, item_categories).
- [x] Validate all keys present and no hardcoded overrides.
- [x] Create `data/schema/` directory.

## 2. Timeline logic (in `data/generate.py`, or `data/timeline.py` if split)
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

## 4. Dimension generation (`data/generate.py`)
- [ ] Load and strictly validate config (raise on missing key).
- [ ] Initialize single seeded RNG (`np.random.default_rng(seed)`).
- [ ] Generate `manufacturers` (`scale.manufacturers` rows).
- [ ] Generate `distribution_centers` (`scale.distribution_centers` rows).
- [ ] Generate `items` (`scale.items` rows) with drift hooks.
- [ ] Generate base customers (`scale.base_customers` rows) at month 1.
- [ ] Generate growth-phase customer adds (`scale.growth_adds_per_month`).
- [ ] Assign churn months for decline phase.
- [ ] Snapshot dimension attributes at generation time.
- [ ] Add `customers.currency` (ISO-4217) for FX gap support.

## 5. Transactional generation — clean months (`data/generate.py`)
- [ ] Global ID counters for all tables.
- [ ] Monthly order header generation (vectorized).
- [ ] Monthly order line generation (1–4 lines per order).
- [ ] Enforce `(order_id, item_id)` uniqueness.
- [ ] Generate shipments per order.
- [ ] Generate shipment_lines linked to order_line_id.
- [ ] Handle month-end spillover for ship dates.
- [ ] Generate invoices per order.
- [ ] Generate invoice_lines per order line.
- [ ] Handle month-end spillover for invoice dates.
- [ ] Generate ar_ledger (1:1 with invoices).
- [ ] Generate backorders for under-shipped lines.
- [ ] Generate returns 1–2 months after shipments.
- [ ] Ensure clean months (1–6) have zero defects.

## 6. GL and FX tables (`data/generate.py`)
- [ ] Generate `gl_revenue` at `(period, account_id, item_category)` grain
  with nullable `customer_id` (top-N only); rows derived from
  `scale.gl_accounts × scale.item_categories` (sampled).
- [ ] Set recognized revenue from billings baseline.
- [ ] Generate `fx_rates` (`scale.currencies × n_months`).
- [ ] Add load_date and version columns.

## 7. Defect injection (in `data/generate.py`, or `data/defects.py` if split)
- [ ] Implement defect logging helper with exact required fields.
- [ ] Implement `orphaned_item_id`.
- [ ] Implement `duplicate_invoice_line`.
- [ ] Implement `missing_customer_mapping`.
- [ ] Implement `stale_load`.
- [ ] Implement `billings_gl_variance`.
- [ ] Implement `restatement`.
- [ ] Implement `fx_gap`.
- [ ] Implement `orphaned_backorder`.
- [ ] Implement `phantom_return`.
- [ ] Distribute defects across months ≥ enabled_from_month.
- [ ] Concentrate defects at month-end/handoff days.
- [ ] Ensure each `row_key` points to a real row.

## 8. Manifest (folded into `data/generate.py`)
- [ ] Assemble manifest with required fields.
- [ ] Compute SHA-256 per parquet file.
- [ ] Compute size_bytes per file.
- [ ] Count defects by type.
- [ ] Write ISO `generated_at` timestamp.

## 9. Output writing (`data/generate.py`)
- [ ] Create `data/runs/<name>/` directory.
- [ ] Write all 15 Parquet tables (sorted, index=False) with all months.
- [ ] Write `defects.json`.
- [ ] Write `manifest.json`.
- [ ] Ensure output < 2 GB.

## 10. README (`data/README.md`)
- [ ] How to run section.
- [ ] New scenario creation section.
- [ ] Verification queries section.
- [ ] Scenario examples (baseline_run, severe_decline, churn_spike).

## 11. Verification & reproducibility
- [ ] Run `python data/generate.py --config data/config.yaml`.
- [ ] Confirm all 15 tables + defects.json + manifest.json exist.
- [ ] Confirm months 1–6 have zero defects.
- [ ] Confirm months 7+ defect count meets minimum.
- [ ] Confirm `ar_ledger` rows == `invoices` rows.
- [ ] Confirm all defect `row_key` values resolve.
- [ ] Rerun and compare Parquet hashes (byte-identical).
- [ ] Compare manifests (identical except `generated_at`).
- [ ] Test seed change produces different data, same defect counts.
- [ ] Test phase change produces different volume arc.
- [ ] Check total size < 2 GB.
- [ ] Check total Python LOC < 1,500.

## 12. Final cleanup
- [ ] Remove temporary files.
- [ ] Final review of diff.
- [ ] Commit if applicable.
