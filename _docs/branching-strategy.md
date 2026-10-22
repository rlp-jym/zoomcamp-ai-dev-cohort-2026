# Branching Strategy

This repository follows a three-branch promotion flow:

- `develop` — integration branch for all ongoing work. Feature branches are
  created from `develop` and merged back via pull request.
- `staging` — pre-production. Merges from `develop` trigger the staging
  deploy workflow.
- `main` — production. Merges from `staging` trigger the production deploy
  workflow, which requires manual approval through the GitHub `production`
  environment.

## Flow

```
feature/*  ->  develop  ->  staging  ->  main
```

1. Create a feature branch from `develop` (use a clean prefix such as
   `feat/`, `fix/`, `chore/`, `ci/`, `docs/`).
2. Open a pull request into `develop`. CI tests must pass.
3. When `develop` is ready for release, open a pull request into `staging`.
   Merging to `staging` deploys to the staging Render service.
4. After validation in staging, open a pull request into `main`. Merging to
   `main` deploys to production after manual approval.

## Rules

- Do not push directly to `main`, `staging`, or `develop`.
- Do not create randomly named branches; use the prefixes above.
- Delete feature branches after merge.
- Keep `develop` up to date with `main` when hotfixes land.
