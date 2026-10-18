# Revenue Data Reliability Platform

## Synthetic data generator

Hypothetical test fixtures live under `data/`. They are not part of the application itself.

- Run: `uv run --project data python data/generate.py --config data/config.yaml`
  (or double-click `run_generator.bat` and enter a seed)
- Output: `data/runs/<name>/` — 15 Parquet tables + `defects.json` + `manifest.json`
- See `data/README.md` for full usage, scenarios, and verification queries.