import type { Preferences, State, Status } from './types'
import { liveFixture } from './mocks/live'
import { betweenGamesFixture } from './mocks/betweenGames'
import { idleFixture } from './mocks/idle'

const rawFlag = import.meta.env.VITE_USE_MOCK as string | undefined
export const useMock: boolean = rawFlag === undefined ? true : rawFlag !== '0' && rawFlag.toLowerCase() !== 'false'

export type MockName = Status

let selectedMock: MockName = 'live'
let staleOverride: boolean | null = null

export function setMockSelection(name: MockName): void {
  selectedMock = name
}

export function getMockSelection(): MockName {
  return selectedMock
}

export function setStaleOverride(value: boolean | null): void {
  staleOverride = value
}

export function getStaleOverride(): boolean | null {
  return staleOverride
}

function baseFixture(name: MockName): State {
  if (name === 'live') return liveFixture
  if (name === 'between_games') return betweenGamesFixture
  return idleFixture
}

export function mockState(): State {
  const base = baseFixture(selectedMock)
  const clone: State = JSON.parse(JSON.stringify(base)) as State
  if (staleOverride !== null) {
    clone.stale = staleOverride
  }
  return clone
}

const mockPreferences: Preferences = {
  pinned_match_id: null,
  view_mode: 'standard',
}

function loadMockPreferences(): Preferences {
  try {
    const raw = window.localStorage.getItem('nexus.preferences')
    if (raw !== null) {
      const parsed = JSON.parse(raw) as Preferences
      if (parsed.view_mode === 'standard' || parsed.view_mode === 'deep') {
        mockPreferences.view_mode = parsed.view_mode
      }
      mockPreferences.pinned_match_id = parsed.pinned_match_id ?? null
    }
  } catch {
    // Keep defaults; storage failure must not break the board.
  }
  return { ...mockPreferences }
}

export async function fetchState(): Promise<State> {
  if (useMock) {
    return mockState()
  }
  const res = await fetch('/api/state')
  if (!res.ok) {
    throw new Error(`GET /api/state failed: ${res.status}`)
  }
  return (await res.json()) as State
}

export async function fetchPreferences(): Promise<Preferences> {
  if (useMock) {
    return loadMockPreferences()
  }
  const res = await fetch('/api/preferences')
  if (!res.ok) {
    throw new Error(`GET /api/preferences failed: ${res.status}`)
  }
  return (await res.json()) as Preferences
}

export async function putPreferences(prefs: Preferences): Promise<Preferences> {
  if (useMock) {
    mockPreferences.view_mode = prefs.view_mode
    mockPreferences.pinned_match_id = prefs.pinned_match_id
    try {
      window.localStorage.setItem('nexus.preferences', JSON.stringify(mockPreferences))
    } catch {
      // Ignore persistence failure in mock mode.
    }
    return { ...mockPreferences }
  }
  const res = await fetch('/api/preferences', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(prefs),
  })
  if (!res.ok) {
    throw new Error(`PUT /api/preferences failed: ${res.status}`)
  }
  return (await res.json()) as Preferences
}
