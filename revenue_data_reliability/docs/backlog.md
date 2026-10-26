# Backlog

## Remove Generator from Repo — 2026-10-27

Decision: the three seed bundles are fixed fixtures in Filebase. The repo no
longer generates or uploads data.

### Done

- [x] Removed `data/` from the repo index; kept locally and ignored.
- [x] Removed `run_generator.py`, `run_generator.bat`, `upload.py` from the index.
- [x] Removed `backend/services/backfill.py` from the index.
- [x] Removed `.github/workflows/scenario-generate.yml` from the index.
- [x] Removed `gh_token` from `backend/config.py`.
- [x] Removed `GH_TOKEN` from `.env.example`.
- [x] Updated `README.md`, `docs/architecture.md`, `docs/deployment.md`,
      `docs/demo.md`, `docs/spec.md`, `infra/R2.md`, `infra/SECRETS.md`,
      and `AGENTS.md`.
- [x] Disclosed the removal in the architecture Deviations table and the
      README Sample Datasets note.

### Manual

- [ ] Remove `GH_TOKEN` and `APP_URL` from GitHub Actions secrets.
- [ ] Remove `GH_TOKEN` and `APP_URL` from Render environment variables
      (staging and prod).
- [ ] Confirm `scenario-generate` disappears from GitHub Actions after the push.
- [ ] Optional: add `.dockerignore` entries for the local-only files.
- [ ] Optional: archive the local generator copies outside the repo.
