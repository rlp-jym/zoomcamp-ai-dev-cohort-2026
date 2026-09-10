```markdown
# AGENTS.md — Nexus

Root context for the codebase.

## Authority

Two documents, two jobs. Nothing is duplicated between them.

| Document | Owns |
|---|---|
| `_docs/specs.md` | **Design.** Requirements, architecture rationale, edge-state behavior, API contract. |
| This file | **Procedure and constraints.** Invariants, data flow, polling, config, build order, conventions. |

`_docs/specs.md` is authoritative for design. This file is authoritative for
procedure. If a nested `AGENTS.md` conflicts with this file, this file wins —
fix the nested file.

Read order for any task: this file, then the `AGENTS.md` nearest the file you
are editing (`backend/` or `frontend/`), then `_docs/specs.md` for rationale.

---

## 1. What this is

Nexus is a **local, single-user, live scoreboard for League of Legends
esports.** It auto-detects the currently-running professional match, pulls live
stats from Riot's public lolesports feed, and renders a broadcast-style
scoreboard on a local screen.

It is **not** a betting product, not a multi-user service, not a stats archive.
No odds. No accounts. No history.

### The six invariants

These override everything else. If a change would violate one, stop and ask.

1. **The board never goes blank.** Unknown values render as `—`. Absent data
   renders the idle or between-games screen. There is no fourth case.
2. **The board never crashes.** Every external call is wrapped. A failure logs
   and backs off. The UI is unaffected.
3. **A failed poll never clears state.** Last known values stay on screen.
4. **Unknown is `null`, never `0`, `""`, or `NaN`.** Backend sends `null`;
   frontend renders `—`.
5. **No new dependency without asking.** Both dependency lists are deliberate.
6. **Scope cuts stay cut.** §3 lists what was cut and why.

---

## 2. Architecture

Two runtimes, one job each.

- **Backend** — Python 3.12+, `uv`, FastAPI. Polls Riot, normalizes to a single
  state object, serves it as JSON, persists preferences.
- **Frontend** — React + TypeScript + Vite, plain CSS. Polls the backend once
  per second and renders.

**Why a backend exists at all:** Riot's lolesports endpoints send no CORS
headers. A browser cannot call them directly. The backend fetches and re-serves
over `localhost`. This is not negotiable.

### Repo layout

```
nexus/
├── AGENTS.md                 # this file
├── dev.sh                    # runs both processes
├── .gitignore
├── backend/
│   ├── AGENTS.md
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── .env.example
│   ├── .nexus/preferences.json   # gitignored, created at runtime
│   ├── src/nexus/
│   │   ├── __init__.py
│   │   ├── main.py           # FastAPI app, routes, lifespan
│   │   ├── config.py         # env -> Settings
│   │   ├── state.py          # in-memory current state
│   │   ├── poller.py         # adaptive loop
│   │   ├── riot/
│   │   │   ├── __init__.py
│   │   │   ├── client.py     # HTTP, auth, timeout, retry
│   │   │   ├── models.py     # pydantic models
│   │   │   └── normalize.py  # raw -> state, frame diffing
│   │   └── storage/
│   │       ├── __init__.py
│   │       ├── base.py       # PreferencesRepository protocol
│   │       └── json_file.py  # default adapter
│   └── tests/
│       ├── fixtures/
│       └── test_*.py
└── frontend/
    ├── AGENTS.md
    ├── package.json
    ├── tsconfig.json
    ├── vite.config.ts
    ├── index.html
    └── src/
        ├── main.tsx
        ├── App.tsx
        ├── api.ts
        ├── types.ts
        ├── components/
        │   ├── StandardBoard.tsx
        │   ├── DeepPanel.tsx
        │   ├── TeamColumn.tsx
        │   ├── ObjectivesRow.tsx
        │   └── IdleScreen.tsx
        └── styles/
            ├── index.css
            └── *.css
```

---

## 3. Scope

### In scope

- One live match at a time, auto-detected, with manual pin override
- **Standard** view (primary): team name/code/logo/color, series score, best-of,
  game number, game clock, kills, gold, towers, dragons, barons
- **Deep** view (secondary panel): per-player rows (role, champion, K/D/A, CS,
  items) and objective spawn timers
- Three edge states (§8)
- Preferences persistence only

### Out of scope — do not build

- Betting, odds, markets, wallets, settlement
- Schedules browsing, standings, playoffs, next-match countdowns
- Game history, stats persistence, any archival storage
- Multi-user access, auth, accounts, remote viewers
- Frontend tests
- Animation, sound, event callouts
- LPL special-casing (see §7)
- Pre-game picks panel

If asked to add any of these, confirm first. They were deliberate cuts.

---

## 4. Data flow

This is the exact sequence. Do not improvise.

### Startup

1. Load settings from env (§10). **If `RIOT_API_KEY` is unset, exit with code 1
   and print:** `RIOT_API_KEY is not set. Copy backend/.env.example to
   backend/.env and fill it in.`
2. Load preferences from `backend/.nexus/preferences.json`. If the file does
   not exist, create it with defaults: `{"pinned_match_id": null,
   "view_mode": "standard"}`.
3. Start the poller as an asyncio background task (FastAPI `lifespan`).
4. Serve the API on `NEXUS_PORT`.

### Every poller tick

1. **Determine `matchId`:**
   - If `pinned_match_id` is set in preferences, use it.
   - Else `GET getLive`. Take the first event where `state == "inProgress"`.
     If none, set state to `idle` (§8) and return.
2. `GET getEventDetails?id={matchId}`. This returns the match and its `games`.
3. **Find the in-progress game:** the entry in `games` where
   `state == "inProgress"`.
   - **Found** → `gameId` = that game's `id`. Go to step 4.
   - **Not found, but the match itself is in progress** → set state to
     `between_games` (§8) and return.
   - **Match not found or not in progress** → set state to `idle` and return.
4. **Fetch live stats:** `GET livestats/v1/window/{gameId}` with
   `startingTime` computed per §6.
5. Normalize the response into the state object (`_docs/specs.md` §9 shape).
6. Atomically replace the in-memory state.
7. Sleep for the interval from §6.

### On any error in steps 1–5

Log at `warning`. **Do not modify the state object.** Sleep per the backoff in
§6.

---

## 5. Data source

Riot's public lolesports endpoints. Free, no registration, no paid tier.
Unofficial and undocumented — hence the tolerance rules.

| Purpose | Endpoint |
|---|---|
| Live matches | `https://esports-api.lolesports.com/persisted/gw/getLive?hl=en-US` |
| Event details | `https://esports-api.lolesports.com/persisted/gw/getEventDetails?hl=en-US&id={matchId}` |
| Live window | `https://feed.lolesports.com/livestats/v1/window/{gameId}?startingTime={iso}` |

**Auth:** header `x-api-key: {RIOT_API_KEY}` on every request. The key is
supplied by the human via env. **Do not attempt to discover, guess, or verify
it.** If it is missing, fail per §4 step 1. If the API returns 403, log a
warning telling the human the key may have rotated, and back off — do not
retry at full rate.

**Timeouts:** every request uses an explicit 10s timeout. `httpx` has no
default timeout; omitting one is a bug.

---

## 6. Polling and time alignment

### Intervals

| Condition | Interval |
|---|---|
| Game in progress (`status == "live"`) | `POLL_LIVE_SECONDS` (default 10) |
| Between games (`status == "between_games"`) | `POLL_BETWEEN_SECONDS` (default 30) |
| Nothing live (`status == "idle"`) | `POLL_IDLE_SECONDS` (default 60) |
| After an error | exponential: 10 → 20 → 40 → … capped at `POLL_MAX_BACKOFF_SECONDS` (default 300) |

Backoff resets to the normal cadence **only after a successful poll**. An HTTP
204 counts as success.

### `startingTime` alignment

The window feed requires a `startingTime` aligned to a 10-second boundary.
Compute it exactly like this — do not improvise:

```python
from datetime import datetime, timezone

def aligned_starting_time(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    floored = now.replace(microsecond=0, second=now.second - (now.second % 10))
    return floored.strftime("%Y-%m-%dT%H:%M:%S.000Z")
```

This helper lives in `riot/client.py`. Call it in one place.

---

## 7. Known data caveats

Real, load-bearing. Do not "fix" these by guessing.

1. **No CORS.** Hence the backend (§2).
2. **Anti-spoiler delay** of a few dozen seconds. Expected. Not a bug.
3. **LPL returns HTTP 204** from the livestats feed. **Do not special-case LPL
   by name.** Treat 204 generically as "no data": keep the series score,
   leave game stats null. This is the accepted behavior.
4. **`startingTime` must be 10s-aligned** (§6).
5. **The feed is undocumented and can change without notice.** Every parser
   must tolerate missing and null fields. **A schema surprise degrades the
   display; it never kills the poller.**

---

## 8. Edge states

**Authoritative definition: `_docs/specs.md` §8.**

Summary, for orientation only — do not treat this as the definition:

- `idle` — nothing live. Render the holding screen.
- `between_games` — series live, no game in progress. Render the series view.
- `stale` — a poll failed. A boolean flag, orthogonal to `status`. Retains last
  known values; never clears state.

Exactly three `status` values exist. No others.

The exact strings, formats, and rendering rules are in the spec. **If this
summary and the spec disagree, the spec wins** — fix this summary.

---

## 9. API contract

**Authoritative definition: `_docs/specs.md` §9.** The endpoint table, the
exact `GET /api/state` response shape, and the contract rules all live there.

Two rules that matter enough to restate here:

- Every field that can be unknown is `null`. Never drop a key to signal
  unknown.
- The frontend polls `/api/state` once per second. This is deliberately
  decoupled from the Riot poll cadence and must not be "optimized" away.

The endpoint list is small and fixed. Adding a field to `/api/state` is a
contract change — both runtimes must change together.

---

## 10. Configuration

Env vars, read in `backend/src/nexus/config.py` via pydantic-settings. Never
hardcode.

`backend/.env.example`:

```dotenv
# Required. Get this from lolesports.com — open DevTools, watch a request to
# esports-api.lolesports.com, copy the x-api-key header value.
RIOT_API_KEY=

NEXUS_PORT=8000
STORAGE_BACKEND=json
POLL_LIVE_SECONDS=10
POLL_BETWEEN_SECONDS=30
POLL_IDLE_SECONDS=60
POLL_MAX_BACKOFF_SECONDS=300
```

| Var | Default | Notes |
|---|---|---|
| `RIOT_API_KEY` | *(none)* | Required. App exits if unset. |
| `NEXUS_PORT` | `8000` | |
| `STORAGE_BACKEND` | `json` | `json` \| `postgres` |
| `POLL_LIVE_SECONDS` | `10` | |
| `POLL_BETWEEN_SECONDS` | `30` | |
| `POLL_IDLE_SECONDS` | `60` | |
| `POLL_MAX_BACKOFF_SECONDS` | `300` | |

---

## 11. Storage

**Preferences only.** No history. No stats. No archival data.

### Interface

```python
# backend/src/nexus/storage/base.py
from typing import Protocol

class PreferencesRepository(Protocol):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str) -> None: ...
    def all(self) -> dict[str, str]: ...
```

### Default adapter

`JsonFilePreferencesRepository` writes to `backend/.nexus/preferences.json`.
The directory is created on first write. The file is gitignored.

### Database-agnostic requirement

All application code depends on the protocol, **never on file I/O directly.**
Adding Postgres later = one new adapter file + one config value. Not a refactor.

**Keep this thin.** No migrations, no connection pooling, no ORM, no generic
query layer. One tiny schema. Anything more is speculative and should be
rejected.

---

## 12. Build order

Build in this sequence. Do not start a step before the previous one runs.

1. **Backend skeleton** — `pyproject.toml`, `config.py`, `main.py` with a
   `/api/state` returning a hardcoded idle state. `uv run nexus` serves it.
2. **Storage** — `base.py`, `json_file.py`, tests. Wire into `main.py`.
3. **Riot client** — `client.py` with `get_live`, `get_event_details`,
   `get_window`, and `aligned_starting_time`. No parsing yet.
4. **Record fixtures** — run the client once against a live match, save raw
   JSON to `tests/fixtures/`. **Do this before writing any parser.**
5. **Models + normalize** — `models.py` and `normalize.py` written against
   the recorded fixtures, not against guesses. Tests use the fixtures.
6. **Poller** — `poller.py` per §4 and §6. Wire into lifespan.
7. **Frontend skeleton** — Vite + React + TS, `types.ts` mirroring
   `_docs/specs.md` §9, `api.ts` polling `/api/state` once per second,
   rendering raw JSON.
8. **StandardBoard** — per §8 and the frontend `AGENTS.md`.
9. **IdleScreen + between-games** — the three states.
10. **DeepPanel** — per-player rows and objective timers.
11. **`dev.sh`** — runs backend and frontend together.

---

## 13. Commands

### Backend

```bash
cd backend
uv sync
uv run nexus
uv run pytest
uv run ruff check . && uv run ruff format .
uv run mypy src
```

### Frontend

```bash
cd frontend
npm install
npm run dev
npm run build
npm run typecheck
```

### Both

`dev.sh` at the repo root:

```bash
#!/usr/bin/env bash
set -euo pipefail
trap 'kill 0' EXIT

(cd backend && uv run nexus) &
(cd frontend && npm run dev) &

wait
```

`chmod +x dev.sh`.

### Dependency lists — these exact packages, nothing else

**`backend/pyproject.toml`** runtime: `fastapi`, `uvicorn[standard]`, `httpx`,
`pydantic`, `pydantic-settings`. Dev: `pytest`, `pytest-asyncio`, `ruff`,
`mypy`.

**`frontend/package.json`** runtime: `react`, `react-dom`. Dev: `vite`,
`@vitejs/plugin-react`, `typescript`, `@types/react`, `@types/react-dom`.

**HTTP stubbing in tests:** use `httpx.MockTransport` (already available, no
new dependency). Do not add `respx`.

**`[project.scripts]`** in `pyproject.toml` must define `nexus =
"nexus.main:run"`, and `run()` must start uvicorn on `NEXUS_PORT`.

---

## 14. Testing

**Backend only.** No frontend tests. Do not add them.

**Never hit the live Riot API from a test.** Recorded fixtures only.

Cover at minimum:

- `client.py` — parses responses with missing and null fields
- `normalize.py` — raw → state; frame-to-frame diffing into events
- Edge-state transitions: live → between_games → idle; error → stale → recovery
- `json_file.py` — round-trip `get` / `set` / `all`
- `aligned_starting_time` — boundary cases at :00, :09, :10, :59

Fixtures live in `backend/tests/fixtures/` as raw JSON, saved verbatim, named
for what they exercise (`window_missing_gold.json`, `window_204.json`).

Test the ugly inputs. The happy path is the least interesting test here.

---

## 15. Conventions

- **Python:** `ruff` lint + format, `mypy --strict` on `src/`. Type everything.
  `X | None` over `Optional[X]`. No `# type: ignore` without a justifying
  comment — handle the `None` case instead. `logging`, never `print`.
- **TypeScript:** `strict: true`. No `any`. No `!` on API data. No `as` casts
  to paper over nullability. If the type is wrong, fix `types.ts`.
- All external I/O wrapped. A failed call logs and returns `None`; it never
  raises into the poller and never clears state.
- Small pure functions in `normalize.py`. No HTTP, no disk, no clock reads —
  pass time in as an argument.
- Nullable API fields are genuinely nullable. The frontend renders `—`.

---

## 16. Definition of done

A change is complete when all of these hold:

1. `uv run ruff check .` clean
2. `uv run ruff format .` produces no diff
3. `uv run mypy src` clean
4. `uv run pytest` passes
5. `npm run typecheck` clean
6. `npm run build` succeeds
7. No new dependency was added without asking
8. No error path can clear state or blank the board
9. No nullable field renders as `NaN`, `undefined`, or `0`
```