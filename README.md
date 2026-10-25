# DataTalksClub — AI Dev Tools Zoomcamp 2026

Course homework and final project submissions.

## Final Project

**Revenue Data Reliability Platform** — ingest, validate, reconcile, and publish
B2B revenue data with a team of AI agents and human approval gates.

| | |
|---|---|
| Project | [`revenue_data_reliability/`](revenue_data_reliability/) |
| README | [`revenue_data_reliability/README.md`](revenue_data_reliability/README.md) |
| Docs | [`revenue_data_reliability/docs/`](revenue_data_reliability/docs/) |
| Live demo | https://revenue-platform-prod.onrender.com |
| Health | https://revenue-platform-prod.onrender.com/health |

## Quick Demo

1. Open Validation (`/runs`), choose persona **FP&A Analyst**, load **Seed 1 (Neutral)**.
2. Click **Validate**, review the run on Validation (`/runs/{id}`).
3. Switch to **FP&A Manager**, approve go-live.
4. Open Dashboard (`/`); use Data Issues (`/exceptions`) to clear blockers.

## Branches

| Branch | Purpose |
|---|---|
| `develop` | Active development |
| `staging` | Deploy preview |
| `main` | Production |

CI/CD workflows live at the repository root (`.github/workflows/`).

## Homework

`homework_1/` … `homework_4/`.
