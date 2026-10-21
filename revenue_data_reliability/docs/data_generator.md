# Data generator

Hypothetical synthetic revenue dataset used as test fixtures for this platform. Not part of the application.

- Location: `data/`
- Entry point: `uv run --project data python data/generate.py --config data/config.yaml`
- Or double-click `run_generator.bat` (prompts for seed; blank = random)
- Output: `data/runs/<name>/` with 16 Parquet tables (incl. `budget`), `defects.json`, `manifest.json`
- Span: 5 years (60 months); defects injected from month 7
- Reproducible: same seed + config = byte-identical output
- Size: < 2 GB
- `data/sample/` is reference-only and not committed