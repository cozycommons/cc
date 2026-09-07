import { describe, expect, it } from 'vitest';
import { computeTournamentStandings } from './utils.js';

const player = (id, name) => ({ user_id: id, display_name: name, avatar_url: null });

function game(winnerTeam, team1, team2) {
  return {
    winner_team: winnerTeam,
    players: [
      { ...team1[0], team: 1 },
      { ...team1[1], team: 1 },
      { ...team2[0], team: 2 },
      { ...team2[1], team: 2 },
    ],
  };
}

describe('computeTournamentStandings', () => {
  it('tallies wins and losses from completed games', () => {
    const tournament = {
      enrolled_players: [player('u1', 'Jason'), player('u2', 'Priya'), player('u3', 'Marcus'), player('u4', 'Wei')],
      completed_games: [
        game(1, [player('u1', 'Jason'), player('u2', 'Priya')], [player('u3', 'Marcus'), player('u4', 'Wei')]),
        game(2, [player('u1', 'Jason'), player('u2', 'Priya')], [player('u3', 'Marcus'), player('u4', 'Wei')]),
      ],
    };

    const standings = computeTournamentStandings(tournament);
    const byId = Object.fromEntries(standings.map((s) => [s.user_id, s]));

    expect(byId.u1).toMatchObject({ wins: 1, losses: 1 });
    expect(byId.u3).toMatchObject({ wins: 1, losses: 1 });
  });

  it('ranks by wins desc, then losses asc, then name', () => {
    const tournament = {
      enrolled_players: [player('u1', 'Jason'), player('u2', 'Priya')],
      completed_games: [
        game(1, [player('u1', 'Jason'), player('u3', 'X')], [player('u2', 'Priya'), player('u4', 'Y')]),
      ],
    };

    const standings = computeTournamentStandings(tournament);
    expect(standings[0].user_id).toBe('u1');
    expect(standings[0].wins).toBe(1);
  });

  it('breaks ties in favor of Jaycee over other tied players', () => {
    const tournament = {
      enrolled_players: [player('u1', 'Aziz'), player('u2', 'Jaycee'), player('u3', 'Andrew')],
      completed_games: [],
    };

    const standings = computeTournamentStandings(tournament);
    expect(standings.map((s) => s.display_name)).toEqual(['Jaycee', 'Andrew', 'Aziz']);
  });

  it('includes enrolled players with no games yet at 0-0', () => {
    const tournament = {
      enrolled_players: [player('u1', 'Jason')],
      completed_games: [],
    };

    const standings = computeTournamentStandings(tournament);
    expect(standings).toEqual([expect.objectContaining({ user_id: 'u1', wins: 0, losses: 0 })]);
  });

  it('includes players who played but are not in enrolled_players', () => {
    const tournament = {
      enrolled_players: [],
      completed_games: [
        game(1, [player('u1', 'Jason'), player('u2', 'Priya')], [player('u3', 'Marcus'), player('u4', 'Wei')]),
      ],
    };

    const standings = computeTournamentStandings(tournament);
    expect(standings).toHaveLength(4);
  });

  it('sums self sinks across completed games, defaulting to 0', () => {
    const tournament = {
      enrolled_players: [player('u1', 'Jason'), player('u2', 'Priya')],
      completed_games: [
        {
          winner_team: 1,
          players: [
            { ...player('u1', 'Jason'), team: 1, self_sinks: 2 },
            { ...player('u3', 'X'), team: 1, self_sinks: 1 },
            { ...player('u2', 'Priya'), team: 2, self_sinks: 0 },
            { ...player('u4', 'Y'), team: 2 },
          ],
        },
        {
          winner_team: 2,
          players: [
            { ...player('u1', 'Jason'), team: 1, self_sinks: 1 },
            { ...player('u3', 'X'), team: 1, self_sinks: 0 },
            { ...player('u2', 'Priya'), team: 2, self_sinks: 3 },
            { ...player('u4', 'Y'), team: 2 },
          ],
        },
      ],
    };

    const standings = computeTournamentStandings(tournament);
    const byId = Object.fromEntries(standings.map((s) => [s.user_id, s]));

    expect(byId.u1.self_sinks).toBe(3);
    expect(byId.u2.self_sinks).toBe(3);
    expect(byId.u4.self_sinks).toBe(0);
  });

  it('excludes only substitute players from group-stage standings', () => {
    const tournament = {
      enrolled_players: [player('u1', 'Matthew'), player('u2', 'Shrey'), player('u3', 'Jason'), player('u4', 'Warner')],
      completed_games: [{
        winner_team: 1,
        players: [
          { ...player('u1', 'Matthew'), team: 1, counts_for_group_stage: false },
          { ...player('u2', 'Shrey'), team: 1 },
          { ...player('u3', 'Jason'), team: 2 },
          { ...player('u4', 'Warner'), team: 2 },
        ],
      }],
    };

    const byId = Object.fromEntries(computeTournamentStandings(tournament).map((s) => [s.user_id, s]));
    expect(byId.u1).toMatchObject({ wins: 0, losses: 0 });
    expect(byId.u2).toMatchObject({ wins: 1, losses: 0 });
    expect(byId.u3).toMatchObject({ wins: 0, losses: 1 });
    expect(byId.u4).toMatchObject({ wins: 0, losses: 1 });
  });
});
