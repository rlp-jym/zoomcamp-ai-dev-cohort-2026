# Neon Database Setup

> As-built: the staging and production Render services are configured to use a
> Neon `DATABASE_URL`. `infra/render.yaml` still declares Render Postgres
> (`rlp-db-staging` / `rlp-db-prod`); reconcile that blueprint in Phase 2.

## Staging and Production Databases

Create two Neon projects (or two databases in one project):

- `rlp_staging` (for the staging Render service)
- `rlp_prod` (for the production Render service)

## Connection Strings

Set `DATABASE_URL` in the corresponding Render service to the Neon connection
string (with `?sslmode=require`). The app calls `init_pool()` on boot and runs
`apply_schema()` (idempotent `CREATE TABLE IF NOT EXISTS`).

## Local Development

Use the Postgres service from `infra/docker-compose.yml` (database `rlp`,
user `postgres`). Or point `DATABASE_URL` at a Neon dev database.

## Schema Initialization

`backend/db/schema.sql` is applied on startup by `apply_schema()`. No manual
migration step is required for v1.
