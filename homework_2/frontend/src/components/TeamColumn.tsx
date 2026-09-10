import type { Team } from '../types'
import { formatGold, show } from '../format'
import '../styles/TeamColumn.css'

interface TeamColumnProps {
  team: Team
  kills: number | null
  gold: number | null
  towers: number | null
  barons: number | null
  dragons: string[] | null
  side: 'home' | 'away'
}

export function TeamColumn({ team, kills, gold, towers, barons, dragons, side }: TeamColumnProps): JSX.Element {
  const accent = team.color ?? 'var(--border)'
  const dragonText =
    dragons === null ? '—' : dragons.length === 0 ? '0' : `${dragons.length} · ${dragons.join(', ')}`
  return (
    <section className="team-column" style={{ borderTopColor: accent }} aria-label={team.name}>
      <div className="team-name-row">
        {team.logo !== null && team.logo !== '' ? (
          <img className="team-logo" src={team.logo} alt={`${team.code} logo`} />
        ) : (
          <span className="team-logo-fallback" aria-hidden="true">
            {show(team.code)}
          </span>
        )}
        <div>
          <div className="team-name">{show(team.name)}</div>
          <div className="team-code">{show(team.code)}</div>
        </div>
      </div>
      <dl className="team-stats">
        <div className="stat">
          <dt>K</dt>
          <dd>{show(kills)}</dd>
        </div>
        <div className="stat">
          <dt>G</dt>
          <dd>{formatGold(gold)}</dd>
        </div>
        <div className="stat">
          <dt>T</dt>
          <dd>{show(towers)}</dd>
        </div>
        <div className="stat">
          <dt>B</dt>
          <dd>{show(barons)}</dd>
        </div>
        <div className="stat stat-wide">
          <dt>D</dt>
          <dd data-testid={`dragons-${side}`}>{dragonText}</dd>
        </div>
      </dl>
    </section>
  )
}
