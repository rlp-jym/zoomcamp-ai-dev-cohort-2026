# AGENTS.md – ChoreFairness (Couple's Dashboard)

## Project Context
- **User**: Couple/partners (high-trust, low-friction).
- **Primary goal**: Track perceived effort to prevent resentment, using trend lines over time.
- **Effort definition**: Subjective rating (1–10) per chore instance.
- **Assignment model**: Each chore has a default owner, but owners can swap (manual edit).
- **Fairness view**: Trend lines comparing cumulative effort over days/weeks.

## MVP Scope (Web Dashboard)
- **Chore list** with default owner field (editable).
- **Daily log** – record chore done + subjective effort rating.
- **Trend view** – line chart (7/14/30 days) showing each partner's cumulative effort.
- **Fairness indicator** – percentage difference displayed alongside trend.

## Tech Stack (suggested)
- Backend: Node.js / Python (Flask or FastAPI) + SQLite/Postgres.
- Frontend: React or Vanilla JS + Chart.js for trends.
- Persistence: Database (local or hosted).

## Out of Scope (for this deliverable)
- User accounts / multi-session auth (use shared session or local storage).
- Push notifications, gamification, auto-rotation, scheduling.
- Mobile app or CLI.

## Deliverable
A working web app with at least two routes (log view + trends) that persists data across refreshes. No login required – single shared household view.