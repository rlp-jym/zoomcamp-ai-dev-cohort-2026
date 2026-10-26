# Secrets

Required environment variables / secrets:

- `DATABASE_URL` — Postgres connection string.
- `R2_ENDPOINT_URL`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET` —
  S3-compatible object storage credentials.
- `GROQ_API_KEY` — optional; when empty the agents fall back to template
  responses.
- `WEBHOOK_TOKEN` — shared secret for the scenario registration webhook.
- `APP_ENV` — `dev`, `staging`, or `prod`.

Store these in GitHub Actions secrets (`R2_*`, `GROQ_API_KEY`, `WEBHOOK_TOKEN`,
`RENDER_*_DEPLOY_HOOK`) and in Render's environment variables.
Never commit secret values to the repository.
