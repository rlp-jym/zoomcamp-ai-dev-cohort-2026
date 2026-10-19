# AGENTS.md — Revenue Data Reliability Platform (project_1)

Scope: entire `project_1/`. The data generator lives under `data/` and has its own `data/AGENTS.md`.

## Purpose
Revenue Data Reliability Platform. Synthetic test fixtures are produced by `data/` generator.

## Conventions
- Directories and files use snake_case (e.g., `run_generator.py`, `data_generator.md`).
- Do not commit generated artifacts: `data/runs/`, `data/sample/`, `.venv/`, `__pycache__/`.
- Data generator rules: see `data/AGENTS.md`.

## Quick links
- Spec (locked): `SPEC.md`
- Metric definitions: `definitions.md`
- Task tracker: `TASKS.md`
- Agent skill definitions: `backend/skills/`
- Generator docs: `data/README.md`
- Generator details: `docs/data_generator.md`
- Orchestrator: `run_generator.bat` / `run_generator.py`