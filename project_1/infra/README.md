# Infra

## Local run (Docker)
From the project root (`project_1/`):

```bash
docker compose -f infra/docker-compose.yml up --build
```

App: http://localhost:8000  (health: /health)
Postgres: localhost:5432 (user postgres / pass postgres / db rlp)

## Render (staging/prod)
`render.yaml` defines a Docker web service + managed Postgres. Set the
sync:false env vars in the Render dashboard (R2_*, GROQ_API_KEY, etc.).

## Required secrets / env vars
- DATABASE_URL
- R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET
- GROQ_API_KEY (optional; template fallback when empty)
- WEBHOOK_TOKEN
- APP_ENV (dev|staging|prod)

## R2 bucket
- Bucket name = R2_BUCKET
- Prefix convention: scenarios/<scenario_name>/*.parquet
- Lifecycle: optional; old run objects can be expired after N days.