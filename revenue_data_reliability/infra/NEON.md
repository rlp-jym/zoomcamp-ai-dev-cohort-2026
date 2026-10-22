# Neon DB setup

## Staging and production databases

Create two Neon projects (or two databases in one project):

- `rlp_staging` (for the staging Render service)
- `rlp_prod` (for the production Render service)

## Connection strings

Set `DATABASE_URL` in the corresponding Render service to the Neon connection
string (with `?sslmode=require`). The app calls `init_pool()` on boot and runs
`apply_schema()` (idempotent `CREATE TABLE IF NOT EXISTS`).

## Local development

Use the Postgres service from `infra/docker-compose.yml` (database `rlp`,
user `postgres`). Or point `DATABASE_URL` at a Neon dev database.

## Schema initialization

`backend/db/schema.sql` is applied on startup by `apply_schema()`. No manual
migration step is required for v1.
