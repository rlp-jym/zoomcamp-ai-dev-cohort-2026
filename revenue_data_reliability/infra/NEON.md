# Neon Database Setup

> Confirmed in the Render dashboard: both staging and production use a Neon
> `DATABASE_URL` (`postgresql://neondb_owner…`). Env vars are managed manually;
> Blueprint sync is optional/paid. `infra/render.yaml` is a reference and uses
> `DATABASE_URL: sync: false`; the legacy `databases:` block remains until the
> unused Render DBs are backed up and removed.

## Staging and Production Databases

Create two Neon projects (or two databases in one project):

- `rlp_staging` (for the staging Render service)
- `rlp_prod` (for the production Render service)

## Connection Strings

Set `DATABASE_URL` in the corresponding Render service to the Neon connection
string (with `?sslmode=require`). The app calls `init_pool()` on boot and runs
`apply_schema()` (idempotent `CREATE TABLE IF NOT EXISTS`).

## Local Development

Use the Postgres service from `docker-compose.yml` (database `rlp`,
user `postgres`). Or point `DATABASE_URL` at a Neon dev database.

## Schema Initialization

`backend/db/schema.sql` is applied on startup by `apply_schema()`. No manual
migration step is required for v1.
