import type { State } from '../types'

export const betweenGamesFixture: State = {
  status: 'between_games',
  stale: false,
  lastUpdated: '2026-09-10T12:20:00Z',
  match: {
    id: 'lec-2026-winter-g2-vs-fnc',
    bestOf: 3,
    gameNumber: null,
    nextGameNumber: 3,
    seriesScore: { home: 1, away: 1 },
    teams: {
      home: {
        name: 'G2 Esports',
        code: 'G2',
        logo: null,
        color: '#E6002B',
      },
      away: {
        name: 'Fnatic',
        code: 'FNC',
        logo: null,
        color: '#FF5900',
      },
    },
  },
  game: null,
}
