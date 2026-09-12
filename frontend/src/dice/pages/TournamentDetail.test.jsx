import { describe, expect, it } from 'vitest';

import { selectBracketTeamPlayer } from './TournamentDetail.jsx';

describe('tournament bracket team selection', () => {
  it('keeps singles teams to exactly one player after selecting them', () => {
    expect(selectBracketTeamPlayer([null], 0, 'player-1', true)).toEqual(['player-1']);
    expect(selectBracketTeamPlayer(['old-player', null], 0, 'player-2', true)).toEqual(['player-2']);
  });

  it('updates only the selected doubles slot', () => {
    expect(selectBracketTeamPlayer(['player-1', 'player-2'], 1, 'player-3', false))
      .toEqual(['player-1', 'player-3']);
  });
});
