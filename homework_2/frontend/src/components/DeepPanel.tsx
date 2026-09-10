import type { Game, MatchInfo } from '../types'
import { formatClock, show } from '../format'
import '../styles/DeepPanel.css'

interface DeepPanelProps {
  match: MatchInfo
  game: Game
}

export function DeepPanel({ match, game }: DeepPanelProps): JSX.Element {
  return (
    <section className="deep-panel" aria-label="Deep panel">
      <div className="deep-teams">
        {(['home', 'away'] as const).map((side) => (
          <div className="deep-team" key={side}>
            <h3 className="deep-team-name">{show(match.teams[side].name)}</h3>
            <table className="deep-table">
              <thead>
                <tr>
                  <th scope="col">Role</th>
                  <th scope="col">Champion</th>
                  <th scope="col">K</th>
                  <th scope="col">D</th>
                  <th scope="col">A</th>
                  <th scope="col">CS</th>
                  <th scope="col">Items</th>
                </tr>
              </thead>
              <tbody>
                {game.players[side].map((player, index) => (
                  <tr key={`${player.role}-${index}`}>
                    <td>{show(player.role)}</td>
                    <td>{show(player.champion)}</td>
                    <td>{show(player.kills)}</td>
                    <td>{show(player.deaths)}</td>
                    <td>{show(player.assists)}</td>
                    <td>{show(player.cs)}</td>
                    <td className="deep-items">
                      {player.items.length === 0
                        ? '—'
                        : player.items.map((item) => `#${item}`).join(' ')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </div>
      <div className="deep-timers" aria-label="Objective spawn timers">
        <span>
          Dragon: <strong>{formatClock(game.objectiveTimers.dragon)}</strong>
        </span>
        <span>
          Baron: <strong>{formatClock(game.objectiveTimers.baron)}</strong>
        </span>
      </div>
    </section>
  )
}
