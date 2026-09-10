import type { Game, MatchInfo } from '../types'
import { TeamColumn } from './TeamColumn'
import { ObjectivesRow } from './ObjectivesRow'
import '../styles/StandardBoard.css'

interface StandardBoardProps {
  match: MatchInfo
  game: Game
}

export function StandardBoard({ match, game }: StandardBoardProps): JSX.Element {
  return (
    <div className="standard-board">
      <div className="team-columns">
        <TeamColumn
          team={match.teams.home}
          kills={game.kills.home}
          gold={game.gold.home}
          towers={game.towers.home}
          barons={game.barons.home}
          dragons={game.dragons.home}
          side="home"
        />
        <TeamColumn
          team={match.teams.away}
          kills={game.kills.away}
          gold={game.gold.away}
          towers={game.towers.away}
          barons={game.barons.away}
          dragons={game.dragons.away}
          side="away"
        />
      </div>
      <ObjectivesRow game={game} homeCode={match.teams.home.code} awayCode={match.teams.away.code} />
    </div>
  )
}
