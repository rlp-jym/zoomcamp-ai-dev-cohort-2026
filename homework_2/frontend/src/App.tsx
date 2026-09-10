import { useEffect, useState } from 'react'
import {
  fetchPreferences,
  fetchState,
  getMockSelection,
  putPreferences,
  setMockSelection,
  setStaleOverride,
  useMock,
} from './api'
import { formatClock, show } from './format'
import type { MatchInfo, Preferences, State, Status } from './types'
import { StandardBoard } from './components/StandardBoard'
import { DeepPanel } from './components/DeepPanel'
import { IdleScreen } from './components/IdleScreen'
import './styles/App.css'

const showDevControls = import.meta.env.DEV && useMock

function bestOfLabel(bestOf: number | null): string {
  if (bestOf === null) {
    return '—'
  }
  return `BO${bestOf}`
}

function Header({ state }: { state: State }): JSX.Element | null {
  if (state.match === null) {
    return (
      <header className="app-header">
        <span className="header-title">Nexus</span>
        {state.stale ? <span className="stale-dot" title="Stale — showing last known values" aria-label="Stale" /> : null}
      </header>
    )
  }
  const match: MatchInfo = state.match
  const gameNumberText =
    state.status === 'live' ? `GAME ${show(match.gameNumber)}` : null
  return (
    <header className="app-header">
      <span className="header-title">Nexus</span>
      <span className="header-score">
        {show(match.teams.home.code)} {match.seriesScore.home} — {match.seriesScore.away}{' '}
        {show(match.teams.away.code)}
      </span>
      <span className="header-meta">
        {bestOfLabel(match.bestOf)}
        {gameNumberText !== null ? ` · ${gameNumberText}` : null}
        {state.status === 'live' && state.game !== null ? ` · ${formatClock(state.game.clockSeconds)}` : null}
      </span>
      {state.stale ? <span className="stale-dot" title="Stale — showing last known values" aria-label="Stale" /> : null}
    </header>
  )
}

function BetweenGames({ match }: { match: MatchInfo }): JSX.Element {
  return (
    <section className="between-games" aria-label="Between games">
      <p className="between-score">
        {show(match.teams.home.name)} {match.seriesScore.home} – {match.seriesScore.away}{' '}
        {show(match.teams.away.name)}
      </p>
      <p className="between-next">game {show(match.nextGameNumber)} starting…</p>
    </section>
  )
}

function DevControls({
  mockName,
  staleOn,
  onSelect,
  onToggleStale,
}: {
  mockName: Status
  staleOn: boolean
  onSelect: (name: Status) => void
  onToggleStale: () => void
}): JSX.Element {
  return (
    <div className="dev-controls" aria-label="Mock controls">
      <span className="dev-label">Mock:</span>
      {(['live', 'between_games', 'idle'] as const).map((name) => (
        <button
          key={name}
          type="button"
          className={mockName === name ? 'dev-button dev-button-active' : 'dev-button'}
          onClick={() => onSelect(name)}
        >
          {name}
        </button>
      ))}
      <button
        type="button"
        className={staleOn ? 'dev-button dev-button-active' : 'dev-button'}
        onClick={onToggleStale}
        aria-pressed={staleOn}
      >
        stale: {staleOn ? 'on' : 'off'}
      </button>
    </div>
  )
}

export function App(): JSX.Element {
  const [state, setState] = useState<State | null>(null)
  const [fetchError, setFetchError] = useState(false)
  const [viewMode, setViewMode] = useState<Preferences['view_mode']>('standard')
  const [mockName, setMockName] = useState<Status>(() => getMockSelection())
  const [staleOn, setStaleOn] = useState(false)

  useEffect(() => {
    let cancelled = false
    async function loadPreferences(): Promise<void> {
      try {
        const prefs = await fetchPreferences()
        if (!cancelled) {
          setViewMode(prefs.view_mode)
        }
      } catch {
        // Keep the default view mode; a preferences failure never clears state.
      }
    }
    void loadPreferences()
    async function pollOnce(): Promise<void> {
      try {
        const next = await fetchState()
        if (!cancelled) {
          setState(next)
          setFetchError(false)
        }
      } catch {
        // Keep the last good state and set a local error flag.
        if (!cancelled) {
          setFetchError(true)
        }
      }
    }
    void pollOnce()
    const timer = window.setInterval(() => {
      void pollOnce()
    }, 1000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [])

  async function toggleViewMode(): Promise<void> {
    const next: Preferences['view_mode'] = viewMode === 'standard' ? 'deep' : 'standard'
    setViewMode(next)
    try {
      await putPreferences({ pinned_match_id: null, view_mode: next })
    } catch {
      // View toggle already applied locally; persistence failure is ignored.
    }
  }

  function handleSelectMock(name: Status): void {
    setMockSelection(name)
    setMockName(name)
  }

  function handleToggleStale(): void {
    const next = !staleOn
    setStaleOn(next)
    setStaleOverride(next ? true : null)
  }

  function renderBody(current: State): JSX.Element {
    switch (current.status) {
      case 'live': {
        if (current.match === null || current.game === null) {
          return <IdleScreen />
        }
        return (
          <>
            <StandardBoard match={current.match} game={current.game} />
            {viewMode === 'deep' ? <DeepPanel match={current.match} game={current.game} /> : null}
          </>
        )
      }
      case 'between_games': {
        if (current.match === null) {
          return <IdleScreen />
        }
        return <BetweenGames match={current.match} />
      }
      case 'idle': {
        return <IdleScreen />
      }
    }
  }

  return (
    <div className="app">
      {state === null ? (
        <IdleScreen />
      ) : (
        <>
          <Header state={state} />
          <main className="app-main">{renderBody(state)}</main>
          <footer className="app-footer">
            <button type="button" className="view-toggle" onClick={() => void toggleViewMode()}>
              {viewMode === 'standard' ? 'Show Deep panel' : 'Show Standard view'}
            </button>
            {fetchError ? (
              <span className="fetch-error">Connection issue — showing last known values</span>
            ) : null}
          </footer>
        </>
      )}
      {showDevControls ? (
        <DevControls
          mockName={mockName}
          staleOn={staleOn}
          onSelect={handleSelectMock}
          onToggleStale={handleToggleStale}
        />
      ) : null}
    </div>
  )
}
