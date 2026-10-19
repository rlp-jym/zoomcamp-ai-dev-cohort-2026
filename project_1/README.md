# Revenue Data Reliability Platform

## Problem Statement
A platform that ingests synthetic B2B-distribution revenue data, validates it,
reconciles billings to GL, and surfaces exceptions via a team of AI agents and
human discussion.

## Current Status
Frontend skeleton complete with stub data; backend and database wiring in progress.

## How to Run (Local)
`uvicorn backend.main:app --reload`

## Documentation Links
- Architecture & Scope: `SPEC.md`
- Metric Definitions & KPI Rationale: `definitions.md`
- Build Roadmap: `TASKS.md`