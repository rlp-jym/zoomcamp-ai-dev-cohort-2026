```markdown
# AGENTS.md — backend

Scoped rules for `backend/`. **The root `AGENTS.md` is authoritative — read it
first.** This file adds only what is specific to Python. It must not duplicate
root content; if a rule here conflicts with the root, the root wins.

Root sections you will need: §4 Data flow, §6 Polling, §7 Caveats, §11 Storage,
§13 Dependency lists, §14 Testing.

**API contract: `_docs/specs.md` §9.** That is the authoritative shape. Root
§9 is a pointer.

---

## Tooling

- **Python 3.12+**, managed by **uv**. Never `pip`, never `python -m venv`,
  never `poetry`.
- `uv sync` to install. `uv run <cmd>` to execute. `uv add <pkg>` to add a
  dependency — but §13 of the root fixes the dependency list, so **ask before
  adding anything.**
- src layout: package at `backend/src/nexus/`. Import as `nexus.*`.
- Commit both `pyproject.toml` and `uv.lock`. Never hand-edit `uv.lock`.

## Commands

```bash
cd backend
uv sync
uv run nexus
uv run pytest
uv run pytest tests/test_normalize.py -k dragon
uv run ruff check . && uv run ruff format .
uv run mypy src
```

`ruff` and `mypy` must be clean before a task is done.

---

## `riot/client.py`

- Every request has an **explicit 10s timeout.** Omitting one is a bug —
  `httpx` has no default.
- `x-api-key` comes from settings. **Never inline it.** Never log it.
- **Wrap every call in try/except.** On failure: log at `warning`, return
  `None`. Never raise into the poller.
- **HTTP 204 means "no data," not an error.** Return `None` without logging a
  warning. This is the generic gap case; do not check for LPL by name.
- **HTTP 403** logs a warning naming possible key rotation. Back off; do not
  retry at full rate.
- `aligned_starting_time()` per root §6 lives here. One definition, one call
  site.

## `riot/models.py`

- pydantic models for the raw payloads.
- **Every non-essential field is optional.** A missing field must not raise.
- Write models against the recorded fixtures in `tests/fixtures/`, not against
  assumptions. If a fixture and a model disagree, the fixture wins.
- Model names mirror the payload nesting (`WindowFrame`, `WindowTeam`,
  `EventDetails`, `LiveEvent`).

## `riot/normalize.py`

This is where bugs live and where tests pay off.

- **Pure functions only.** Raw payload in, plain dataclass or dict out. No
  HTTP, no disk, no clock reads — pass time in as an argument.
- **Never invent values.** Unknown → `None`. Not `0`, not `""`.
- Keep **mapping** separate from **diffing**. Mapping turns a frame into state;
  diffing compares two frames and produces events. Each testable alone.
- A missing required field yields a **partial state, never an exception.**
- Champion IDs and item IDs stay as raw IDs. Do not add a static data lookup —
  it is out of scope.

## `poller.py`

- Intervals come from settings. Never hardcode `10`, `30`, `60`, `300`.
- Backoff is exponential and capped at `POLL_MAX_BACKOFF_SECONDS`. Reset only
  after a **successful** poll. A 204 counts as success.
- **The loop never exits on error.** Log, back off, retry.
- Write state via an **atomic swap** or under a lock. Never mutate the object
  the API is reading.
- The tick sequence is root §4, verbatim. Do not add steps.

## `main.py`

- FastAPI with a `lifespan` that starts and stops the poller task.
- `run()` is the entry point referenced by `[project.scripts]`. It reads
  `NEXUS_PORT` from settings and starts uvicorn. It also performs the startup
  checks in root §4.
- **Startup check: if `RIOT_API_KEY` is unset, exit(1) with the exact message
  in root §4.** Do not start the server with a missing key.
- Routes match `_docs/specs.md` §9 exactly. **Do not add fields to
  `/api/state` casually.**
- Every field that can be unknown is `null` in the response. Never drop a key.
- **No auth. No SSE. No WebSockets.** These are deliberate.
- `PUT /api/selection` with `{"matchId": null}` unpins. Persist immediately.

## `storage/`

- All access goes through `PreferencesRepository` (root §11). **Never call
  `open()`, `json.load`, or `Path.write_text` outside this package.**
- `JsonFilePreferencesRepository` writes to `backend/.nexus/preferences.json`,
  creating the directory if needed.
- Keep the interface to the three methods in root §11. **No migrations, no
  pooling, no ORM, no generic query layer.**
- If a change would make "add a Postgres adapter = one file + one config value"
  untrue, it is out of scope. Ask first.

---

## Conventions

- `ruff` lint and format. `mypy --strict` on `src/`. Type everything including
  private helper return types.
- **No `# type: ignore`** without a comment explaining why the `None` case
  cannot be handled. Blanket ignores hide real bugs.
- `X | None` over `Optional[X]`. `dict` / `list` over `Dict` / `List`.
- `logging` with a module-level logger. **No `print` in `src/`.** (`main.py`
  startup errors may use `sys.stderr.write` — they happen before logging is
  configured.)

---

## Testing

- **Never hit the live Riot API from a test.** Not once.
- Fixtures are raw JSON saved verbatim, named for what they exercise.
- Cover the root §14 list.
- **Test the ugly inputs** first: missing fields, nulls, empty participant
  arrays, truncated frames, 204, 403, 500, timeouts.
- **HTTP stubbing: `httpx.MockTransport`.** No `respx`, no other mocking
  library.
- `pytest` + `pytest-asyncio` only.
```