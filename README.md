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

1. Open Validation (`/runs`); pick **FP&A Analyst** in the header persona selector.
2. Load Dataset → choose **Seed 1 (Neutral)**, **Seed 2 (Bullish)**, or **Seed 3 (Bearish)** → **Load**.
3. Click **Validate** next to that dataset. Results load automatically at the bottom of the page.
4. Switch to **FP&A Manager**, open Data Issues (`/exceptions`), and resolve or dismiss open issues — go-live is blocked while any stay open.
5. Click **Approve Go-Live** in the validation run results.
6. Open Dashboard (`/`) — published data, charts, threads.
7. Each chart carries its own discussion thread — post there to debate KPIs with any persona.

## Branches

| Branch | Purpose |
|---|---|
| `develop` | Active development |
| `staging` | Deploy preview |
| `main` | Production |

CI/CD workflows live at the repository root (`.github/workflows/`).

## Homework

`homework_1/` … `homework_4/`.
