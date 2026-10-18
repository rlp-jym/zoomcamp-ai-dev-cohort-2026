# Synthetic Revenue Dataset Generator

Config-driven, seeded, reproducible synthetic revenue dataset used as test
fixtures for the Revenue Data Reliability Platform.

## How to run

```bash
uv run --project data python data/generate.py --config data/config.yaml
```

Output is written to `data/runs/<config.name>/` and contains 15 Parquet tables
plus `defects.json` and `manifest.json`.

Requirements: Python with `pandas`, `pyarrow`, `pyyaml` (see `data/pyproject.toml`).

## New scenario creation

1. Copy `data/config.yaml` to a new file (e.g. `data/config_severe.yaml`).
2. Adjust `name`, `seed`, `timeline.phases`, `scale.*`, and `defects.*`.
3. Run:

```bash
uv run --project data python data/generate.py --config data/config_severe.yaml
```

The `name` field selects the output directory under `data/runs/`.

## Verification queries

After a run, sanity-check with:

```python
import pandas as pd, json
run = "data/runs/baseline_run"
orders = pd.read_parquet(f"{run}/orders.parquet")
invoices = pd.read_parquet(f"{run}/invoices.parquet")
ar = pd.read_parquet(f"{run}/ar_ledger.parquet")
defects = json.load(open(f"{run}/defects.json"))
print("tables ok; ar==invoices:", len(ar) == len(invoices))
print("defects:", len(defects))
print("months with defects:", sorted({d["injected_month"] for d in defects}))
```

## Scenario examples

- `baseline_run` — default config (`data/config.yaml`): 36 months, growth →
  plateau → decline, moderate defects from month 7.
- `severe_decline` — shorten growth, lengthen decline, raise churn; expect
  lower volumes in late months.
- `churn_spike` — concentrate churn in decline phase; expect rising
  `churned` customer counts and falling order counts.