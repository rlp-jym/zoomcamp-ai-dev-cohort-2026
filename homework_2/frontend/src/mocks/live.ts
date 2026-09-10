import type { State } from '../types'

export const liveFixture: State = {
  status: 'live',
  stale: false,
  lastUpdated: '2026-09-10T12:34:56Z',
  match: {
    id: 'lck-2026-spring-t1-vs-gen',
    bestOf: 5,
    gameNumber: 3,
    nextGameNumber: null,
    seriesScore: { home: 1, away: 1 },
    teams: {
      home: {
        name: 'T1',
        code: 'T1',
        logo: null,
        color: '#E2012D',
      },
      away: {
        name: 'Gen.G',
        code: 'GEN',
        logo: null,
        color: '#AA8B56',
      },
    },
  },
  game: {
    clockSeconds: 1447,
    kills: { home: 12, away: 9 },
    gold: { home: 47200, away: 44800 },
    towers: { home: 6, away: 4 },
    dragons: { home: ['infernal', 'ocean'], away: null },
    barons: { home: 0, away: 1 },
    players: {
      home: [
        { role: 'TOP', champion: 'Aatrox', kills: 3, deaths: 2, assists: 4, cs: 231, items: [6631, 3047, 3078] },
        { role: 'JGL', champion: 'Vi', kills: 2, deaths: 1, assists: 7, cs: 168, items: [6692, 3047] },
        { role: 'MID', champion: 'Azir', kills: 4, deaths: 2, assists: 3, cs: 262, items: [6655, 3020, 3089] },
        { role: 'ADC', champion: 'Zeri', kills: 3, deaths: 2, assists: 4, cs: 289, items: [6673, 3006, 3031] },
        { role: 'SUP', champion: null, kills: 0, deaths: 2, assists: 9, cs: null, items: [3869, 3050] },
      ],
      away: [
        { role: 'TOP', champion: 'K’Sante', kills: 1, deaths: 3, assists: 5, cs: 218, items: [6632, 3047] },
        { role: 'JGL', champion: 'Sejuani', kills: 1, deaths: 2, assists: 6, cs: 154, items: [6664, 3047] },
        { role: 'MID', champion: 'Hwei', kills: 4, deaths: 2, assists: 2, cs: 251, items: [6655, 3020] },
        { role: 'ADC', champion: 'Aphelios', kills: 3, deaths: 3, assists: 2, cs: 276, items: [6671, 3006] },
        { role: 'SUP', champion: 'Neeko', kills: 0, deaths: 2, assists: 7, cs: 34, items: [3869] },
      ],
    },
    objectiveTimers: { dragon: 45, baron: null },
  },
}
