# Traceability

## Rubric → Evidence

| Criterion | Evidence |
|---|---|
| Problem Description | [`../README.md`](../README.md#the-problem) and [`../README.md`](../README.md#the-value) |
| Product Specification | [`spec.md`](spec.md), [`tasks.md`](tasks.md) |
| Agent Team Specification | [`spec.md`](spec.md) §11, `backend/teams/`, `backend/skills/` |
| Context Management | [`../AGENTS.md`](../AGENTS.md), this docs index |
| Application | `backend/`, `frontend/`, `backend/db/schema.sql`; live URL in README |
| Testing | `tests/`, `.github/workflows/test.yml` |
| Containerization | `infra/Dockerfile`, `docker-compose.yml` |
| Deployment | `infra/render.yaml`; prod URL in README |
| CI/CD | `.github/workflows/test.yml`, `deploy-staging.yml`, `deploy-prod.yml` |
| Observability | `observability/`, `/observability` |
| Alerting on User Impact | `backend/services/alerts.py` (six types, 1 h dedup); `backend/teams/controller.py` (`_raise`, triage note, Director escalation); visible in the run thread and `/audit`; walkthrough in [`demo.md`](demo.md#verified-behavior--controller-and-alerts) |
| On-Call Agent | `backend/teams/controller.py` (`trigger_autonomous_rerun`): `STALE_PUBLISHED` opens a `controller`-triggered run and executes the pipeline; `autonomous_re_run` row in `/audit` |

## Build History

| Phase | Key commits |
|---|---|
| Documentation and repo entry points | `fa86462`, `709c41a` |
| Dashboard layout and charts | `7b706dc` |
| Telemetry caps and observability | `7c2c9e4`, `90dd64d` |
| Dataset-scoped threads and opaque charts | `f242f16`, `a2aecf5` |
| 12-month window and Render stability | `dbad70e`, `0fb328b`, `9bea1c9` |
| Seed design | `6f769c5`, `eb87b04` |
| Segment drift rule | `b618ea3` |
| Controller boot run | `61547b2` |
| Sticky header | `e35be5c` |
| Audit and Observability scope | `87b0eaa` |

## Workarounds

Constraint → workaround → commit evidence: [`challenges.md#workarounds`](challenges.md#workarounds).
