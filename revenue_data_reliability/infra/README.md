# Infra

## Local run (Docker)
From the project root (`revenue_data_reliability/`):

```bash
cp .env.example .env   # optional; Filebase/Groq credentials
docker compose up --build
```

App: http://localhost:8000  (health: /health)
Postgres: localhost:5432 (user postgres / pass postgres / db rlp)

## Render (staging/prod)
`render.yaml` is a reference for the Docker web services; Blueprint sync is
optional/paid, so env vars are managed manually in the Render dashboard. The
live database is Neon via `DATABASE_URL: sync: false`; the legacy
managed-Postgres block remains until it is backed up and removed. Set the
sync:false env vars in the Render dashboard (R2_*, GROQ_API_KEY, etc.).

## Required secrets / env vars
- DATABASE_URL
- R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET
- GROQ_API_KEY (optional; template fallback when empty)
- WEBHOOK_TOKEN
- APP_ENV (dev|staging|prod)

## S3 bucket (Filebase)
- Bucket name = R2_BUCKET
- Prefix convention: scenarios/<scenario_name>/*.parquet
- Lifecycle: optional; old run objects can be expired after N days.