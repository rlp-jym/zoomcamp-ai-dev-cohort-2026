import type { Game } from '../types'
import { formatGold, goldShare } from '../format'
import '../styles/ObjectivesRow.css'

interface ObjectivesRowProps {
  game: Game
  homeCode: string
  awayCode: string
}

export function ObjectivesRow({ game, homeCode, awayCode }: ObjectivesRowProps): JSX.Element {
  const share = goldShare(game.gold.home, game.gold.away)
  const homePct = share === null ? null : Math.round(share * 100)
  const awayPct = homePct === null ? null : 100 - homePct
  return (
    <section className="objectives-row" aria-label="Gold share">
      <span className="gold-team">{homeCode}</span>
      <div className="gold-bar" role="img" aria-label={`Gold ${formatGold(game.gold.home)} vs ${formatGold(game.gold.away)}`}>
        <div
          className="gold-bar-home"
          style={{ width: homePct === null ? '50%' : `${homePct}%` }}
        />
      </div>
      <span className="gold-team">{awayCode}</span>
      <span className="gold-numbers">
        {formatGold(game.gold.home)} · {formatGold(game.gold.away)}
        {awayPct === null ? null : (
          <span className="gold-share"> ({homePct}% / {awayPct}%)</span>
        )}
      </span>
    </section>
  )
}
