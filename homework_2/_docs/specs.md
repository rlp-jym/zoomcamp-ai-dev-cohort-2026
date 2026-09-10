```markdown
# Nexus — Specification

**A local, single-user, live scoreboard for League of Legends esports.**

| | |
|---|---|
| Version | 1.0 |
| Status | Implemented (specification) |
| Audience | Course instructor, future maintainers |

---

## 1. Problem statement

Following a professional League of Legends match means watching a stream, or
reloading a stats site, or keeping a second monitor open. None of these are
good when you want a passive, glanceable display — something you can leave
running on a spare screen and read from across the room.

Official broadcasts are cluttered with commentary, overlays, and content
unrelated to the current game state. Third-party stats sites are built for
browsing, not for ambient display, and typically require an account or show
advertising.

**Nexus exists to answer one question continuously and legibly: what is
happening in the game right now?**

It does this by consuming Riot's public esports data feed and rendering a
broadcast-style scoreboard with no interaction required.

## 2. Goals

1. **Zero-interaction display.** Launch it and it finds the live match on its
   own. No search, no selection, no configuration on each run.
2. **Glanceable.** Legible from across a room. The most important numbers —
   series score, game clock, kills, gold — are the largest elements.
3. **Never blank, never crash.** The board always shows something meaningful,
   including when nothing is live and when the data feed fails.
4. **Minimal footprint.** One local process pair, run with a single command,
   no accounts, no cloud services, no cost.
5. **Honest about unknown data.** When a value is unavailable, say so. Never
   display a fabricated or misleading number.

## 3. Non-goals

These were considered and deliberately excluded. They are not oversights.

| Excluded | Reasoning |
|---|---|
| **Betting, odds, wagering** | Considered early and explicitly dropped. It changes the product from a display into a financial system, which brings licensing, regulation, and a paid odds data feed — all far outside a local scoreboard. |
| **Schedules, standings, playoffs** | The product answers "what is happening now," not "what is happening later." Schedule browsing is a different application with a different UI. |
| **Game history / stats archive** | Requires persistent storage of match data, a query layer, and a history UI. None of it serves the ambient-display goal, and it substantially increases scope. |
| **Multi-user / remote access** | The target user is one person at one screen. Adding auth, sessions, and network exposure adds risk and complexity for no benefit. |
| **Mobile / responsive layout** | The display is a fixed local screen. Optimizing for small viewports would compromise the primary case. |
| **Animations and sound** | Explicitly deprioritized by the user. They are a meaningful amount of frontend work for no functional gain. |
| **Per-player deep analytics** | A small per-player panel is in scope; a full analytics suite is not. |
| **LPL support** | Riot's feed does not provide live stats for the LPL. Rather than special-case it, the application degrades gracefully (see §7.3). |

## 4. Functional requirements

Numbered for testability. Each should be verifiable by observation.

### Match selection

- **FR-1** On launch, the application identifies the currently live
  professional match without user input.
- **FR-2** If multiple matches are live, the first is followed.
- **FR-3** The user may pin a specific match, overriding auto-detection.
- **FR-4** A pinned match persists across application restarts.
- **FR-5** Unpinning returns the application to auto-detection.

### Scoreboard — Standard view

- **FR-6** The Standard view displays, for each team: name, short code, logo,
  and team color.
- **FR-7** The Standard view displays the series score and the best-of format.
- **FR-8** The Standard view displays the current game number.
- **FR-9** The Standard view displays the in-game clock in `M:SS` format.
- **FR-10** The Standard view displays, per team: kills, gold, towers, dragons,
  and barons.
- **FR-11** Gold is displayed in abbreviated form (e.g. `42.1k`), with a
  proportional bar showing the relative share.

### Scoreboard — Deep view

- **FR-12** A secondary Deep panel is available on demand.
- **FR-13** The Deep panel displays, per player: role, champion, kills, deaths,
  assists, creep score, and item IDs.
- **FR-14** The Deep panel displays objective spawn timers for dragon and
  baron.
- **FR-15** The Deep panel's visibility is persisted as a user preference.

### Edge states

- **FR-16** When no match is live, the application displays a holding screen
  reading `No live match`.
- **FR-17** When a series is live but no game is in progress, the application
  displays the series score and the number of the next game, rather than
  blanking.
- **FR-18** When a data fetch fails, the application retains the last known
  values on screen and shows a stale indicator.
- **FR-19** The application never displays a blank or error-only screen in any
  state.

### Data handling

- **FR-20** Unavailable values are transmitted as `null` and rendered as `—`.
- **FR-21** A value is never displayed as `0`, `NaN`, or `undefined` to
  represent "unknown."
- **FR-22** The application polls the data source adaptively, at a faster
  cadence during a live game and a slower cadence when idle.
- **FR-23** Polling backs off exponentially on repeated failure, capped at a
  configured maximum.
- **FR-24** A failed poll does not clear or reset application state.

## 5. Non-functional requirements

- **NFR-1 — Local only.** The application binds to `localhost` and is not
  reachable from the network. No authentication is implemented because no
  remote access is possible.
- **NFR-2 — No cost.** All data sources are free and require no paid tier.
- **NFR-3 — No accounts.** No registration, login, or user identity of any
  kind.
- **NFR-4 — Single command to run.** Both processes start via one script.
- **NFR-5 — Bounded resource use.** Polling respects the data source. Backoff
  prevents hammering an endpoint that is failing.
- **NFR-6 — Tolerant of an undocumented API.** All parsing handles missing and
  null fields without raising.
- **NFR-7 — No secrets in source.** The API key is supplied via environment
  variable and never committed.

## 6. Architecture

Two runtimes, each with a single responsibility.

```
┌─────────────────────┐        ┌──────────────────────┐
│  Python backend     │        │  React frontend      │
│  (uv)               │◄───────┤  (Vite, TypeScript)  │
│                     │  HTTP  │                      │
│  • polls Riot feed  │        │  • renders Standard  │
│  • normalizes state │        │  • toggles Deep      │
│  • serves local API │        │  • polls /api/state  │
│  • persists prefs   │        │                      │
└─────────┬───────────┘        └──────────────────────┘
          │ HTTPS
          ▼
   Riot lolesports public endpoints
```

### 6.1 Why a backend exists

This is the single most important architectural constraint, and it is not
optional.

**Riot's lolesports endpoints do not send CORS headers.** A browser page
cannot call them directly — the request is blocked before it leaves the
browser. A backend is therefore required to fetch the data server-side and
re-serve it over `localhost`.

Any design that attempts a pure client-side application is not viable without
a browser extension or disabling web security. Both were rejected as fragile
and poor practice.

### 6.2 Why two runtimes

Python handles data acquisition and normalization; TypeScript handles
presentation. This split was chosen because:

- The data layer benefits from Python's ecosystem and is a natural place for
  future data work.
- The presentation layer benefits from the component model and Vite's
  tooling.
- The boundary between them is a single JSON endpoint, which keeps the
  interface small and stable.

A single-runtime alternative (Node for everything) was considered and is
viable, but was rejected to keep the parsing and normalization logic in
Python.

### 6.3 Communication

The frontend polls `GET /api/state` once per second.

This is deliberately decoupled from the backend's Riot polling cadence, which
is 10 seconds during a live game. A 1-second client poll against a 10-second
server poll is **not** a defect — it keeps the UI responsive to state
transitions (a game ending, a game starting) without the backend having to
push notifications.

Server-sent events and WebSockets were both considered. Both were rejected as
unnecessary complexity for a single-client, single-endpoint application.

## 7. Data source

### 7.1 Chosen source

**Riot's public lolesports endpoints.** These are the same endpoints used by
`lolesports.com`. They are free, require no registration, and have no paid
tier.

| Purpose | Endpoint |
|---|---|
| Live matches | `esports-api.lolesports.com/persisted/gw/getLive` |
| Event details | `esports-api.lolesports.com/persisted/gw/getEventDetails` |
| Live window feed | `feed.lolesports.com/livestats/v1/window/{gameId}` |

Authentication is a static `x-api-key` header whose value is publicly
observable from browser developer tools on `lolesports.com`.

### 7.2 Alternatives considered

| Option | Why rejected |
|---|---|
| **PandaScore** | Live in-game stats and events require the paid Pro Live tier. The free tier provides schedules only, which do not satisfy FR-6 through FR-14. |
| **Abios / Bayes Esports / Sportradar** | All are commercial, betting-oriented providers. No free tier suitable for this use case. |
| **esport.is** | Free tier is limited to 100 requests/hour and offers insufficient depth for a live scoreboard. |
| **Liquipedia API** | Excellent for historical results and rosters, but it is not a live scoreboard feed. |
| **Tournament platforms** (Toornament, Battlefy) | Provide schedules and results, not live in-game telemetry. |

The official Riot feed was selected because it is the only free source that
provides the live in-game data the scoreboard requires.

### 7.3 Known caveats

These are properties of the source, not defects in Nexus. They are documented
so they are not mistaken for bugs.

1. **No CORS headers.** Necessitates the backend (§6.1).
2. **Anti-spoiler delay.** Live data lags the actual game by a few dozen
   seconds. Acceptable for a scoreboard; unsuitable for anything requiring
   real-time precision.
3. **No LPL coverage.** The live window feed returns HTTP 204 for LPL games.
   Nexus treats 204 generically as "no data" and displays the series score
   with empty game stats. This is the accepted behavior, and no LPL-specific
   code exists.
4. **Undocumented and unstable.** The feed can change without notice. All
   parsing is tolerant of missing and null fields (NFR-6).

### 7.4 A note on payload verification

The exact structure of the window feed and event details payloads was **not**
verified against live responses during design. The specification describes
their shape structurally and from familiarity with the feed, but field names
and nesting may differ in places.

This is addressed by the build order: raw responses are recorded to fixtures
**before** any parser is written, and models are written against those
fixtures rather than against assumptions. See `AGENTS.md` §12.

## 8. Edge state behavior

Exactly three states exist. This section is authoritative.

### 8.1 `idle` — no live match

Rendered by `IdleScreen`, centered:

```
No live match
```

No countdown to the next match. No schedule. Schedules are a non-goal (§3).

### 8.2 `between_games` — series live, no game in progress

Rendered as a series-level view:

```
{home.name}  {homeWins} – {awayWins}  {away.name}
game {nextGameNumber} starting…
```

This state occurs frequently in best-of-three and best-of-five series. Blanking
the board here would make the application look broken during a normal part of
every series.

### 8.3 `stale` — data fetch failed

`stale` is a **boolean flag**, orthogonal to `status`. It can be true in any of
the three states above.

When true, the frontend shows a small indicator in the header. The last known
values remain on screen. **State is never cleared and the board is never
blanked** (FR-24).

## 9. API contract

Local only, unauthenticated, JSON over HTTP.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/state` | Full normalized state. Single source of truth. |
| `GET` | `/api/matches/live` | Currently live matches, for manual pinning. |
| `PUT` | `/api/selection` | Pin or unpin a match. |
| `GET` | `/api/preferences` | Read persisted preferences. |
| `PUT` | `/api/preferences` | Update persisted preferences. |

`GET /api/state` response:

```jsonc
{
  "status": "live" | "between_games" | "idle",
  "stale": false,
  "lastUpdated": "2026-09-10T12:34:56Z",
  "match": {                          // null when status == "idle"
    "id": "string",
    "bestOf": 3,
    "gameNumber": 2,                  // null when between_games
    "nextGameNumber": 3,              // null unless between_games
    "seriesScore": { "home": 1, "away": 0 },
    "teams": {
      "home": { "name": "T1", "code": "T1", "logo": "https://...", "color": "#E2012D" },
      "away": { "name": "Gen.G", "code": "GEN", "logo": "https://...", "color": "#AA8B56" }
    }
  },
  "game": {                           // null unless status == "live"
    "clockSeconds": 1247,
    "kills":   { "home": 7, "away": 4 },
    "gold":    { "home": 42100, "away": 39800 },
    "towers":  { "home": 3, "away": 2 },
    "dragons": { "home": ["infernal", "ocean"], "away": ["cloud"] },
    // null = unknown (feed gap); [] = no dragons taken
    "barons":  { "home": 0, "away": 1 },
    "players": {
      "home": [
        { "role": "TOP", "champion": "Aatrox",
          "kills": 2, "deaths": 1, "assists": 3, "cs": 210,
          "items": [1234, 5678] }
      ],
      "away": []
    },
    "objectiveTimers": { "dragon": 45, "baron": null }
  }
}
```

**Contract rules:**

- Every field that can be unknown is nullable. Unknown is `null` — never a
  dropped key, never `0`, never `""`.
- The frontend renders `null` as `—` (FR-20, FR-21).
- Fields are not added casually; the contract is the interface between two
  runtimes and both sides must change together.

## 10. Persistence

**Preferences only.** No match history, no statistics, no archival data.

Persisted values:

| Key | Type | Purpose |
|---|---|---|
| `pinned_match_id` | `string \| null` | User's pinned match, if any (FR-3, FR-4) |
| `view_mode` | `"standard" \| "deep"` | Deep panel visibility (FR-15) |

### 10.1 Database-agnostic design

Storage is accessed through a thin interface so the backing store can be
replaced without modifying application code:

```python
class PreferencesRepository(Protocol):
    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str) -> None: ...
    def all(self) -> dict[str, str]: ...
```

The default implementation is a JSON file. A Postgres implementation would be
a single additional adapter plus a configuration value.

Two adapters exist: `JsonFilePreferencesRepository` (a JSON file at
`backend/.nexus/preferences.json`) and `SqlAlchemyPreferencesRepository`
(one table, SQLite by default). `STORAGE_BACKEND` (`json` | `sqlalchemy`,
default `sqlalchemy`) selects between them; `DATABASE_URL` points the
SQLAlchemy adapter at its database (default
`sqlite:///.nexus/nexus.db`, resolved against the working directory).

The storage layer uses SQLAlchemy 2.0 so the backing database is a
configuration choice rather than an architectural one. The schema is
deliberately minimal — one table — and tables are created with
`Base.metadata.create_all()` at startup. Do not add Alembic, connection
pool tuning, or any repository layer beyond `PreferencesRepository`.
The original "no ORM" rule is superseded by this one.

## 11. Design decisions

A record of choices made and why. Several of these went against an initial
instinct.

### 11.1 React over Svelte

Svelte was the initial recommendation on the grounds of being lighter and
having less boilerplate — both true, and both largely irrelevant at this
application's size.

The deciding factor was the user's unfamiliarity with both frameworks. React
has substantially more tutorials, community answers, and model familiarity. For
a learning-oriented project, "most help available when stuck" outweighs
"fewest characters to write."

The advantage Svelte holds is real but small enough that it was not worth the
tradeoff.

### 11.2 Plain CSS, no framework

The scoreboard's visual design is bespoke — it is not a collection of standard
UI components. A utility framework or component library would have to be
fought rather than used.

This also keeps the dependency list minimal (NFR-4).

### 11.3 Three edge states, not nine

An early draft enumerated nine edge cases: no live match, between games, fetch
failure, LPL, pre-game, next-match countdown, and others.

This was cut to three. The reasoning: **most of the original list was
speculative.** Next-match countdowns and pre-game panels are features, not edge
states, and they belong to the schedule browsing that is already a non-goal.
LPL needed no special case because generic 204 handling covers it.

What remained were the three situations that genuinely occur and would look
like defects if unhandled: nothing live, a series between games, and a failed
fetch. These are cheap to implement and disproportionately visible.

### 11.4 Backend-only testing

The parsing and frame-diffing logic is where bugs actually live, and it is
testable without a browser. Frontend testing for a single-user display app is
effort that does not return value — the UI is verified by looking at it.

### 11.5 No animation

Explicitly deprioritized by the user. This removed a meaningful amount of
frontend work with no functional loss, since the application's value is in
legible numbers rather than presentation polish.

Trivial CSS transitions on gold bar width and score changes are permitted, as
they cost nothing and reduce visual jarring.

### 11.6 Adaptive polling

A fixed interval was the simpler option. Adaptive polling with exponential
backoff was chosen because the data source is free, undocumented, and
unofficial — there is no contract or rate-limit agreement. Polling politely is
the correct posture toward an endpoint being used without a formal agreement.

The cost is minimal: a few lines of state tracking.

### 11.7 Record fixtures before writing parsers

The single most important process decision. The Riot payloads were not
available for inspection during design, so writing parsers first would have
meant writing them against assumptions.

Instead, the build order requires recording real responses to fixtures **before**
any parsing code exists. This converts an unbounded guessing problem into a
mechanical one. See `AGENTS.md` §12.

## 12. Known limitations

- **Payload shapes are unverified.** See §7.4. The first implementation pass
  may discover structural differences between this specification and the real
  feed. This is expected and is handled by the fixture-first build order.
- **The API key may rotate.** The key is not formally documented or guaranteed.
  If it rotates, the application will receive HTTP 403 and back off. Recovery
  requires the user to supply a new key.
- **No LPL live stats.** Structural to the data source. Not addressable at the
  application level.
- **Anti-spoiler delay.** Inherent to the feed. Data is a few dozen seconds
  behind the live game.
- **Single match only.** Following two matches simultaneously is not supported
  and was not designed for.

## 13. Future work

Deliberately excluded from version 1.0, but the architecture does not preclude
them.

- **Postgres storage adapter.** The interface in §10.1 exists to make this a
  single file plus a configuration value.
- **Additional sports or titles.** The backend's normalization layer is
  game-specific, but the API contract and frontend are not inherently
  LoL-bound.
- **Historical match review.** Would require relaxing the preferences-only
  persistence decision and adding a query layer.
- **Broadcast overlay mode.** A styled variant intended as a browser source in
  streaming software.
```