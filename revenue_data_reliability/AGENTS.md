# AGENTS.md — Revenue Data Reliability Platform (revenue_data_reliability)

Scope: entire `revenue_data_reliability/`. The data generator lives under `data/` and has its own `data/AGENTS.md`.

## Purpose
Revenue Data Reliability Platform. Synthetic test fixtures are produced by `data/` generator.

## Conventions
- Directories and files use snake_case (e.g., `run_generator.py`, `data_generator.md`).
- Do not commit generated artifacts: `data/runs/`, `data/sample/`, `.venv/`, `__pycache__/`.
- Data generator rules: see `data/AGENTS.md`.

## Quick links
- Docs index: `docs/README.md`
- Spec (locked): `docs/spec.md`
- Metric definitions: `docs/definitions.md`
- Task tracker: `docs/tasks.md`
- Operating model: `docs/operating-model.md`
- Engineering challenges: `docs/challenges.md`
- Verified behavior backlog: `docs/backlog.md`
- Agent skill definitions: `backend/skills/`
- Generator docs: `data/README.md`
- Generator agent rules: `data/AGENTS.md`
- Orchestrator: `run_generator.bat` / `run_generator.py`