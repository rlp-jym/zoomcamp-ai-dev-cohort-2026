```markdown
# AGENTS.md — frontend

Scoped rules for `frontend/`. **The root `AGENTS.md` is authoritative — read it
first.** This file adds only what is specific to the UI. If a rule here
conflicts with the root, the root wins.

Root sections you will need: §1 Invariants, §13 Dependency lists.

**Edge states: `_docs/specs.md` §8. API contract: `_docs/specs.md` §9.** Those
are authoritative. Root §8 and §9 are pointers.

---

## Stack

- **React + TypeScript + Vite.** Strict TS.
- **Plain CSS only.** No Tailwind, no CSS-in-JS, no component library, no
  utility framework. Deliberate — the look is bespoke.
- The stack is fixed. Do not propose migrating without asking.

## Commands

```bash
cd frontend
npm install
npm run dev
npm run build
npm run typecheck
```

`npm run typecheck` and `npm run build` must both be clean before a task is
done.

## Dependencies

Exactly: `react`, `react-dom`, `vite`, `@vitejs/plugin-react`, `typescript`,
`@types/react`, `@types/react-dom`.

**No additions without asking.** This includes icon packs, date libraries,
class-name helpers, and animation libraries.

---

## `vite.config.ts`

Dev server proxies `/api` to the backend so there is one origin in development.

```ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
})
```

---

## `types.ts`

Mirror root §9 **exactly**, including nullability. If the backend shape
changes, update this file in the same change.

```ts
export type Status = 'live' | 'between_games' | 'idle'
export type Side = 'home' | 'away'

export interface Team {
  name: string
  code: string
  logo: string | null
  color: string | null
}

export interface Player {
  role: string
  champion: string | null
  kills: number | null
  deaths: number | null
  assists: number | null
  cs: number | null
  items: number[]
}

export interface Game {
  clockSeconds: number | null
  kills: Record<Side, number | null>
  gold: Record<Side, number | null>
  towers: Record<Side, number | null>
  dragons: Record<Side, string[] | null>
  barons: Record<Side, number | null>
  players: Record<Side, Player[]>
  objectiveTimers: { dragon: number | null; baron: number | null }
}

export interface MatchInfo {
  id: string
  bestOf: number | null
  gameNumber: number | null
  nextGameNumber: number | null
  seriesScore: Record<Side, number>
  teams: Record<Side, Team>
}

export interface State {
  status: Status
  stale: boolean
  lastUpdated: string
  match: MatchInfo | null
  game: Game | null
}

export interface Preferences {
  pinned_match_id: string | null
  view_mode: 'standard' | 'deep'
}
```

---

## `api.ts`

**The only file that calls `fetch`.** All backend communication goes through
this module — nothing else in the app touches the network.

### Two modes

`api.ts` has a **mock mode** and a **live mode**, selected by
`import.meta.env.VITE_USE_MOCK`.

| Mode | Behavior |
|---|---|
| `mock` **(default)** | Returns fixture data from `src/mocks/`. No network. |
| `live` | Calls `/api/state` etc. via `fetch`. Requires the backend running. |

**Unset means mock.** The prototype must run with no setup, no backend, and
no env file: `npm install && npm run dev`.

The exported function signatures are **identical in both modes.** Callers do
not know which mode is active. Switching to live mode later is one env var,
not a code change.

### Mock mode

- Fixtures live in `src/mocks/`, one per state: `idle.ts`, `betweenGames.ts`,
  `live.ts`. Each exports a full `State` object matching `_docs/specs.md` §9.
- `mockState()` returns the currently selected fixture.
- **A dev control must exist** to switch fixtures and toggle `stale`
  independently, so every state in the spec is reachable in one click.
  Render it only when `import.meta.env.DEV && useMock`.
- At least one fixture must contain `null` fields, so the `—` rendering path
  is visible rather than theoretical.

### Both modes

- Export `fetchState(): Promise<State>`, `fetchPreferences()`,
  `putPreferences()`.
- `App.tsx` polls `fetchState` **once per second** via `setInterval`. This is
  deliberate and decoupled from the backend's 10s Riot poll. **Do not
  "optimize" it.**
- **On fetch failure, keep the last good state and set a local error flag.**
  Do not clear state. Do not render an error page.
- No React Query, no SWR, no Redux, no Zustand. `useState` + `useEffect`.

---

## Rendering

### The three states

Switch on `status` with an **exhaustive switch**. No default branch — if a
fourth state is ever added, the code must fail to compile rather than render
nothing.

- `idle` → `<IdleScreen />`
- `between_games` → series view (`_docs/specs.md` §8 exact format)
- `live` → `<StandardBoard />` (+ `<DeepPanel />` when toggled)

### Nullability

**Every field in root §9 can be null.** Render `—` for null.

Create one helper and use it everywhere:

```ts
export const show = (v: unknown): string =>
  v === null || v === undefined || (typeof v === 'number' && Number.isNaN(v))
    ? '—'
    : String(v)
```

**Never render `NaN`, `undefined`, `null`, or `0` as a stand-in for unknown.**
This is the most likely source of visible bugs in this app.

### Never compute what the API didn't send

No derived "gold lead", no "total objectives", no client-side aggregation. The
display is dumb; logic lives in the backend where it is tested. The one
permitted exception: computing a **width ratio** for the gold bar. The raw
numbers are still shown as text.

---

## Layout

Grid, full viewport, no scrolling. Dark.

```
┌──────────────────────────────────────────────────┐
│  {home.code}  {homeWins} — {awayWins}  {away.code}   GAME {n}   {clock}  •  │
├────────────────────────┬─────────────────────────┤
│  {home.name}           │  {away.name}            │
│  K {kills}  G {gold}   │  K {kills}  G {gold}    │
│  T {towers}  B {barons}│  T {towers}  B {barons} │
│  D {dragons}           │  D {dragons}            │
├────────────────────────┴─────────────────────────┤
│  [ DeepPanel when view_mode === 'deep' ]          │
└──────────────────────────────────────────────────┘
```

- Header: series score, best-of, game number, game clock. Stale dot at the
  right when `stale` is true (8px circle, `--text-muted`).
- Clock format: `M:SS` (e.g. `24:07`). Gold format: `42.1k`.
- Team columns use the team's `color` as a top border accent only.

---

## Styling

- **Broadcast-lite:** dark background, large bold numerals, team colors as
  accents. Must read from across a room.
- **Team colors are accents only.** Never use a team color as text on a dark
  background without checking contrast — some are near-black.
- **No animation system.** Permitted: CSS `transition` on gold bar width and
  score digit changes, ≤200ms. Not permitted: keyframes, flashes, callouts,
  screen shake, sound. No library for this.
- One CSS file per component. Only global file is `styles/index.css`.

### `styles/index.css` custom properties

These exact names. Do not invent others.

```css
:root {
  --bg: #0b0d10;
  --panel: #14171c;
  --border: #23272e;
  --text: #e8eaed;
  --text-muted: #8b919a;
  --accent: #4c8dff;
}
```

---

## TypeScript

- `strict: true`. **Do not weaken it.**
- No `any`. No `!` on API data. No `as` casts to paper over nullability. If the
  type is wrong, fix `types.ts`.

---

## Testing

**No frontend tests.** Do not add them — not Vitest, not Testing Library, not
Playwright. Do not add test dependencies. Verify by running the app and
looking at it.
```