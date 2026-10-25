# Deployment

## Environments

| Environment | Branch | Service | Database |
|---|---|---|---|
| Local | — | Docker Compose | Postgres 16 container |
| Staging | `staging` | `revenue-platform-staging` | Neon via `DATABASE_URL` |
| Production | `main` | `revenue-platform-prod` | Neon via `DATABASE_URL` |

The services are configured to use a Neon connection string; confirm the
`DATABASE_URL` on each Render service. `infra/render.yaml` still declares Render
Postgres (`rlp-db-staging` / `rlp-db-prod`); reconcile that blueprint in Phase 2.
See [`../infra/NEON.md`](../infra/NEON.md).

## CI/CD

| Workflow | Trigger | Steps |
|---|---|---|
| `test.yml` | PR / push to `develop`, `staging`, `main` | Ruff + pytest against Postgres |
| `deploy-staging.yml` | Push to `staging` | Tests, then Render deploy hook |
| `deploy-prod.yml` | Push to `main` | `production` approval, then Render deploy hook |
| `scenario-generate.yml` | Manual | Generate, upload to R2, register webhook |

## Rollback

| Situation | Action |
|---|---|
| Bad staging deploy | Render → service → **Rollback** to the previous deploy |
| Bad production deploy | Render rollback, or `git revert` on `main` → CI → approve |
| Bad data | Director of FP&A → Validation (`/runs`) → Reset demo data (preserves baseline) |
| Verification | `GET /health` → `{"status":"ok"}` |

## Local Run

```bash
cp .env.example .env          # Windows: Copy-Item .env.example .env
docker compose -f infra/docker-compose.yml up --build
```

App: http://localhost:8000 · Health: `/health` · Postgres: `localhost:5432`.

## Limits

| Limit | Mitigation |
|---|---|
| Render 512 MB | 12-month window, DuckDB 200 MB / 1 thread, local Parquet cache |
| Free Postgres | State-only schema; 30-day telemetry retention |
| R2 free 10 GB | `scenarios/<name>/` prefixes; lifecycle policy optional |
| No background workers | APScheduler in-process |
| No auth | Persona selector; documented non-goal |
