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
