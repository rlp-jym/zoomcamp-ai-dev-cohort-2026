# Deployment

## Environments

| Environment | Branch | Service | Database |
|---|---|---|---|
| Local | — | Docker Compose | Postgres 16 container |
| Staging | `staging` | `revenue-platform-staging` | Neon via `DATABASE_URL` |
| Production | `main` | `revenue-platform-prod` | Neon via `DATABASE_URL` |

Confirmed in the Render dashboard: both services have a `DATABASE_URL` starting
with `postgresql://neondb_owner…`. Env vars are managed manually; Render
Blueprint sync is optional/paid, so `infra/render.yaml` is a reference only.
`DATABASE_URL: sync: false` keeps the manual value; the legacy `databases:`
block remains until the unused Render DBs are backed up and removed. See
[`../infra/NEON.md`](../infra/NEON.md).

## CI/CD

| Workflow | Trigger | Steps |
|---|---|---|
| `test.yml` | PR / push to `develop`, `staging`, `main` | Ruff + pytest against Postgres |
| `deploy-staging.yml` | Push to `staging` | Tests, then Render deploy hook |
| `deploy-prod.yml` | Push to `main` | `production` approval, then Render deploy hook |

## Branch Protection

| Control | State |
|---|---|
| GitHub rulesets | Off during build; re-enable once at final submission |
| Production deploy | Manual approval via the `production` environment |
| Direct pushes | Allowed on `develop` and `staging` during build |

## Rollback

| Situation | Action |
|---|---|
| Bad staging deploy | Render → service → **Rollback** to the previous deploy |
| Bad production deploy | Render rollback, or `git revert` on `main` → CI → approve |
| Bad data | Director of FP&A → Validation (`/runs`) → Reset demo data (preserves baseline) |
| Verification | `GET /health` → `{"status":"ok"}` |

## Local Run

```bash
cp .env.example .env          # optional; Windows: Copy-Item .env.example .env
docker compose up --build
```

App: http://localhost:8000 · Health: `/health` · Postgres: `localhost:5432`.

## Limits

| Limit | Mitigation |
|---|---|
| Render 512 MB | 12-month window, DuckDB 200 MB / 1 thread, local Parquet cache |
| Free Postgres | State-only schema; 30-day telemetry retention |
| Object storage 10 GB | `scenarios/<name>/` prefixes; lifecycle policy optional |
| No background workers | APScheduler in-process |
| No auth | Persona selector; documented non-goal |
