import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ getLiveGame: vi.fn(), getLivePrediction: vi.fn(), getLivePulse: vi.fn(), sendLiveCommand: vi.fn() }));
vi.mock('../api.js', () => ({ diceApi: mocks }));
import LiveGame from './LiveGame.jsx';

const baseGame = {
  id: 'match-1', team_order: ['blue', 'clay'],
  created_at: new Date().toISOString(),
  teams: { blue: ['alice', 'bea'], clay: ['cam', 'dev'] },
  score: [1, 1], status: 'active', version: 7, detail_coverage: 'complete',
  projection: { score: [1, 1], status: 'active', coverage: 'complete' },
  player_names: { alice: 'Alice A', bea: 'Bea B', cam: 'Cam C', dev: 'Dev D' },
  player_avatars: { alice: 'https://img.test/alice.jpg', cam: 'https://img.test/cam.jpg' },
  referees: [{ user_id: 'me', left_at: null }], events: [],
};

function renderGame({ effective = true } = {}) {
  const auth = {
    token: 'token', user: { id: 'me' },
    features: { dice_live_referee: { opted_in: effective, effective } },
  };
  return render(
    <MemoryRouter initialEntries={['/dice/live/match-1']}>
      <Routes><Route path="/dice/live/:matchId" element={<LiveGame auth={auth} />} /></Routes>
    </MemoryRouter>,
  );
}

describe('LiveGame common scoring', () => {
  afterEach(() => vi.resetAllMocks());

  it('does not request game data when the effective flag is off', () => {
    renderGame({ effective: false });
    expect(screen.getByText('Live referee unavailable')).toBeInTheDocument();
    expect(mocks.getLiveGame).not.toHaveBeenCalled();
  });

  it('keeps the score, game state, and thrower dominant without internal metadata', async () => {
    mocks.getLiveGame.mockResolvedValue(baseGame);
    const { container } = renderGame();
    expect(await screen.findByText('1–1')).toBeInTheDocument();
    expect(container.querySelector('.jk-live-status')).toHaveTextContent(/^In progress · 0:0\d$/);
    expect(screen.queryByText(/server v/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/complete detail/i)).not.toBeInTheDocument();
    const alice = screen.getByRole('button', { name: 'Alice A' });
    expect(alice).toHaveAttribute('aria-pressed', 'true');
    expect(alice.querySelector('img')).toHaveAttribute('src', 'https://img.test/alice.jpg');
    const playerNames = new Set(['Alice A', 'Cam C', 'Bea B', 'Dev D']);
    const displayedOrder = within(screen.getByRole('region', { name: 'Live scoring controls' }))
      .getAllByRole('button').map((button) => button.getAttribute('aria-label')).filter((name) => playerNames.has(name));
    expect(displayedOrder).toEqual(['Alice A', 'Bea B', 'Cam C', 'Dev D']);
  });

  it('shows recorded stats with a plain-language incomplete disclosure', async () => {
    mocks.getLiveGame.mockResolvedValue({
      ...baseGame,
      detail_coverage: 'partial',
      projection: { ...baseGame.projection, stats: { point: 2, self_sink: 1, invalid: 1 } },
    });
    renderGame();
    await screen.findByText('1–1');
    expect(screen.queryByRole('region', { name: 'Recorded live stats' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Stats' }));
    expect(screen.getByRole('region', { name: 'Recorded live stats' })).toBeInTheDocument();
    expect(screen.getByText('Points')).toBeInTheDocument();
    expect(screen.getByText('Self-sinks')).toBeInTheDocument();
    expect(screen.getByText('Invalid')).toBeInTheDocument();
    expect(screen.getByText(/Recorded plays only/i)).toBeInTheDocument();
  });

  it('shows a compact per-player summary only after the game is complete', async () => {
    mocks.getLiveGame.mockResolvedValue({
      ...baseGame,
      status: 'completed',
      score: [3, 2],
      detail_coverage: 'partial',
      events: [{ id: 'final-point', kind: 'observation', outcome: 'point', thrower_id: 'alice', sequence: 1 }],
      projection: {
        ...baseGame.projection,
        status: 'completed',
        coverage: 'partial',
        player_stats: {
          alice: { outcomes: { point: 2, sink: 1, self_sink: 1, fifa: 1 }, fifa_goals: 0, fifa_kicks: 0, fifa_catches: 0 },
          bea: { outcomes: {}, fifa_goals: 0, fifa_kicks: 0, fifa_catches: 0, fifa_saves: 1 },
          cam: { outcomes: {}, fifa_goals: 1, fifa_kicks: 2, fifa_catches: 0 },
          dev: { outcomes: {}, fifa_goals: 0, fifa_kicks: 0, fifa_catches: 1 },
        },
      },
    });
    renderGame();

    const summary = await screen.findByRole('region', { name: 'Player game stats' });
    expect(within(summary).getByText('2 points · 1 sink · 1 self-sink · 1 FIFA against')).toBeInTheDocument();
    expect(within(summary).getByText('1 FIFA goal · 2 FIFA kicks')).toBeInTheDocument();
    expect(within(summary).getByText('1 FIFA catch')).toBeInTheDocument();
    expect(within(summary).getByText('1 FIFA save')).toBeInTheDocument();
    expect(within(summary).getByText(/Some plays weren’t recorded./i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Fix this result' })).not.toBeInTheDocument();
    expect(screen.queryByText(/server|canonical|coverage/i)).not.toBeInTheDocument();
  });

  it('does not add player rows to the active referee workflow', async () => {
    mocks.getLiveGame.mockResolvedValue({
      ...baseGame,
      projection: {
        ...baseGame.projection,
        player_stats: {
          alice: { outcomes: { point: 1 }, fifa_goals: 0, fifa_kicks: 0, fifa_catches: 0 },
        },
      },
    });
    renderGame();

    await screen.findByText('1–1');
    expect(screen.queryByRole('region', { name: 'Player game stats' })).not.toBeInTheDocument();
  });

  it('renders a plain-language live estimate without blocking scoring', async () => {
    mocks.getLiveGame.mockResolvedValue(baseGame);
    mocks.getLivePrediction.mockResolvedValue({
      status: 'available', match_version: 7, team1_win_probability: 0.72,
      team2_win_probability: 0.28, model_id: 'elo-score-composition', model_version: '1.0.0',
      pregame_source: 'neutral_fallback',
    });
    renderGame();
    const meter = await screen.findByRole('button', { name: 'Alice & Bea 72 percent, Cam & Dev 28 percent. Open stats' });
    expect(screen.getByRole('button', { name: 'Point' })).toBeEnabled();
    fireEvent.click(meter);
    const pulse = await screen.findByRole('region', { name: 'Stats view' });
    expect(within(pulse).getByText('72%')).toBeInTheDocument();
    expect(within(pulse).getByText('28%')).toBeInTheDocument();
    expect(within(pulse).getByText('Based on the current score')).toBeInTheDocument();
  });

  it('switches locally between fast scoring and stats without losing the thrower', async () => {
    mocks.getLiveGame.mockResolvedValue(baseGame);
    mocks.getLivePulse.mockResolvedValue({
      match_version: 7, model_id: 'elo-score-composition', model_version: '1.0.0',
      pregame_source: 'independent_model_snapshot',
      points: [
        { match_version: 0, score: [0, 0], team1_win_probability: 0.6, team2_win_probability: 0.4, swing: 0, kind: 'start' },
        { match_version: 7, score: [1, 1], team1_win_probability: 0.55, team2_win_probability: 0.45, swing: -0.05, kind: 'play', outcome: 'point', thrower_id: 'cam' },
      ],
      virtual: {
        tournament_id: 't1', balance: 800, rank: 2, field_size: 5,
        pick: { selection: 'blue', stake: 200, potential_return: 333, locked_probability_millionths: 600000, status: 'open' },
      },
    });
    renderGame();

    fireEvent.click(await screen.findByRole('button', { name: 'Cam C' }));
    await waitFor(() => expect(mocks.getLivePulse).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole('button', { name: 'Stats' }));
    const pulse = await screen.findByRole('region', { name: 'Win chance history' });
    expect(within(pulse).getByText('55%')).toBeInTheDocument();
    expect(within(pulse).getByText('45%')).toBeInTheDocument();
    expect(within(pulse).getByText(/Cam point · Cam C \+ Dev D \+5%/)).toBeInTheDocument();
    expect(within(pulse).getByLabelText('Alice A + Bea B down 5 percentage points')).toHaveTextContent('↓ 5%');
    expect(within(pulse).getByLabelText('Cam C + Dev D up 5 percentage points')).toHaveTextContent('↑ 5%');
    expect(within(pulse).getByText('YOUR PICK · Alice A + Bea B')).toBeInTheDocument();
    expect(within(pulse).getByText('800 Dice')).toBeInTheDocument();
    expect(within(pulse).getByText('#2 of 5')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Point' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Referee' }));
    expect(screen.getByRole('button', { name: 'Point' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'Cam C' })).toHaveAttribute('aria-pressed', 'true');
    expect(mocks.getLiveGame).toHaveBeenCalledTimes(1);
    expect(mocks.getLivePulse).toHaveBeenCalledTimes(1);
  });

  it('names the saver as the hero of a scoreless FIFA moment', async () => {
    mocks.getLiveGame.mockResolvedValue(baseGame);
    mocks.getLivePulse.mockResolvedValue({
      match_version: 7, model_id: 'elo-score-composition', model_version: '1.0.0',
      pregame_source: 'independent_model_snapshot',
      points: [
        { match_version: 0, score: [1, 1], team1_win_probability: 0.5, team2_win_probability: 0.5, swing: 0, kind: 'start' },
        {
          match_version: 7, score: [1, 1], team1_win_probability: 0.5, team2_win_probability: 0.5,
          swing: 0, kind: 'play', outcome: 'fifa', thrower_id: 'alice', fifa_finish: 'goal_saved', fifa_actor_id: 'bea',
        },
      ],
    });
    renderGame();

    fireEvent.click(await screen.findByRole('button', { name: 'Stats' }));

    expect(await screen.findByText('Bea saved the FIFA')).toBeInTheDocument();
    expect(screen.queryByText(/Alice.*FIFA/)).not.toBeInTheDocument();
  });

  it('celebrates a correction-safe settled pick with profit, balance, and current rank', async () => {
    mocks.getLiveGame.mockResolvedValue({ ...baseGame, status: 'completed', score: [3, 2] });
    mocks.getLivePulse.mockResolvedValue({
      match_version: 7, model_id: 'elo-score-composition', model_version: '1.0.0',
      pregame_source: 'independent_model_snapshot',
      points: [
        { match_version: 0, score: [0, 0], team1_win_probability: 0.6, team2_win_probability: 0.4, swing: 0, kind: 'start' },
        { match_version: 7, score: [3, 2], team1_win_probability: 1, team2_win_probability: 0, swing: 0.4, kind: 'finish' },
      ],
      virtual: {
        tournament_id: 't1', balance: 1133, rank: 1, field_size: 5,
        pick: { selection: 'blue', stake: 200, potential_return: 333, locked_probability_millionths: 600000, status: 'won' },
      },
    });
    renderGame();

    const pulse = await screen.findByRole('region', { name: 'Win chance history' });
    expect(within(pulse).getByText('WON +133 DICE')).toBeInTheDocument();
    expect(within(pulse).getByText('1133 Dice')).toBeInTheDocument();
    expect(within(pulse).getByText('#1 of 5')).toBeInTheDocument();
    expect(within(pulse).getByText('Final · 3–2')).toBeInTheDocument();
  });

  it('explains a reopened result without presenting it as another scoring play', async () => {
    mocks.getLiveGame.mockResolvedValue(baseGame);
    mocks.getLivePulse.mockResolvedValue({
      match_version: 7, pregame_source: 'independent_model_snapshot',
      points: [
        { match_version: 0, score: [0, 0], team1_win_probability: 0.6, team2_win_probability: 0.4, swing: 0, kind: 'start' },
        { match_version: 7, score: [1, 1], team1_win_probability: 0.55, team2_win_probability: 0.45, swing: 0.55, kind: 'reopen' },
      ],
      virtual: {
        tournament_id: 't1', balance: 1000, rank: 1, field_size: 5,
        pick: { selection: 'blue', stake: 200, potential_return: 333, locked_probability_millionths: 600000, status: 'void' },
      },
    });
    renderGame();

    fireEvent.click(await screen.findByRole('button', { name: 'Stats' }));
    const pulse = await screen.findByRole('region', { name: 'Win chance history' });
    expect(within(pulse).getByText('Reopened · 1–1')).toBeInTheDocument();
    expect(within(pulse).getByText('PICK VOID')).toHaveStyle({ color: 'var(--state-warning)' });
  });

  it('describes a correction as the changed call instead of an unexplained odds swing', async () => {
    mocks.getLiveGame.mockResolvedValue(baseGame);
    mocks.getLivePulse.mockResolvedValue({
      match_version: 7, pregame_source: 'independent_model_snapshot', virtual: null,
      points: [
        { match_version: 0, score: [0, 0], team1_win_probability: 0.57, team2_win_probability: 0.43, swing: 0, kind: 'start' },
        { match_version: 6, score: [1, 0], team1_win_probability: 0.7, team2_win_probability: 0.3, swing: 0.13, kind: 'play', outcome: 'point', thrower_id: 'alice' },
        { match_version: 7, score: [0, 0], team1_win_probability: 0.57, team2_win_probability: 0.43, swing: -0.13, kind: 'correction', outcome: 'miss', thrower_id: 'alice' },
      ],
    });
    renderGame();

    fireEvent.click(await screen.findByRole('button', { name: 'Stats' }));
    const pulse = await screen.findByRole('region', { name: 'Win chance history' });
    expect(within(pulse).getByText('Alice corrected to miss · 0–0')).toBeInTheDocument();
    expect(within(pulse).queryByText(/Correction · .*\+13%/)).not.toBeInTheDocument();
  });

  it('explains an independent pregame estimate without exposing model plumbing', async () => {
    mocks.getLiveGame.mockResolvedValue(baseGame);
    mocks.getLivePrediction.mockResolvedValue({
      status: 'available', match_version: 7, team1_win_probability: 0.72,
      team2_win_probability: 0.28, model_id: 'elo-score-composition', model_version: '1.0.0',
      pregame_source: 'independent_model_snapshot', pregame_model_version: '1.0.0',
    });
    renderGame();
    fireEvent.click(await screen.findByRole('button', { name: 'Stats' }));
    expect(await screen.findByText('Based on pregame win-rate model 1.0.0 and the current score')).toBeInTheDocument();
    expect(screen.queryByText(/ratings not wired yet/i)).not.toBeInTheDocument();
  });

  it('labels a completed probability as a final result', async () => {
    mocks.getLiveGame.mockResolvedValue({ ...baseGame, status: 'completed', score: [3, 2] });
    mocks.getLivePrediction.mockResolvedValue({
      status: 'available', match_version: 7, team1_win_probability: 1,
      team2_win_probability: 0, model_id: 'elo-score-composition', model_version: '1.0.0',
      pregame_source: 'independent_model_snapshot',
    });
    renderGame();
    const finalPrediction = await screen.findByRole('region', { name: 'Live win prediction' });
    expect(within(finalPrediction).getByText('FINAL WIN RESULT')).toBeInTheDocument();
    expect(within(finalPrediction).getByText('100%')).toBeInTheDocument();
    expect(within(finalPrediction).getByText('0%')).toBeInTheDocument();
  });

  it('does not display a prediction older than the canonical score', async () => {
    mocks.getLiveGame.mockResolvedValue({ ...baseGame, version: 8 });
    mocks.getLivePrediction.mockResolvedValue({
      status: 'available', match_version: 7, team1_win_probability: 0.72,
      team2_win_probability: 0.28, model_id: 'elo-score-composition', model_version: '1.0.0',
      pregame_source: 'independent_model_snapshot',
    });
    renderGame();
    await screen.findByText('1–1');
    expect(screen.queryByRole('region', { name: 'Live win prediction' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Open stats/ })).not.toBeInTheDocument();
  });

  it('removes a previously rendered win-chance story when a refresh returns an older story', async () => {
    mocks.getLiveGame
      .mockResolvedValueOnce(baseGame)
      .mockResolvedValueOnce({ ...baseGame, version: 8, score: [2, 1] });
    mocks.getLivePulse
      .mockResolvedValueOnce({
        match_version: 7,
        pregame_source: 'independent_model_snapshot',
        points: [
          { match_version: 0, score: [0, 0], team1_win_probability: 0.6, team2_win_probability: 0.4, swing: 0, kind: 'start' },
          { match_version: 7, score: [1, 1], team1_win_probability: 0.55, team2_win_probability: 0.45, swing: -0.05, kind: 'play' },
        ],
        virtual: null,
      })
      .mockResolvedValueOnce({
        match_version: 7,
        pregame_source: 'independent_model_snapshot',
        points: [{ match_version: 7, score: [1, 1], team1_win_probability: 0.55, team2_win_probability: 0.45, swing: 0, kind: 'play' }],
        virtual: null,
      });
    renderGame();
    fireEvent.click(await screen.findByRole('button', { name: 'Stats' }));
    expect(await screen.findByRole('region', { name: 'Win chance history' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Reload' }));

    expect(await screen.findByText('2–1')).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Win chance history' })).not.toBeInTheDocument();
  });

  it('distinguishes UUID throwers that share the same leading segment', async () => {
    mocks.getLiveGame.mockResolvedValue({ ...baseGame, teams: {
      blue: ['10000000-0000-0000-0000-000000000002', '10000000-0000-0000-0000-000000000003'],
      clay: ['10000000-0000-0000-0000-000000000004', '10000000-0000-0000-0000-000000000005'],
    } });
    renderGame();
    expect(await screen.findByRole('button', { name: /^0002/ })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: /^0005/ })).toBeInTheDocument();
  });

  it('uses server-supplied player names throughout referee controls', async () => {
    mocks.getLiveGame.mockResolvedValue(baseGame);
    renderGame();
    expect(await screen.findByText('Alice & Bea')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /More results/i }));
    fireEvent.change(screen.getByLabelText('Result'), { target: { value: 'fifa' } });
    fireEvent.click(screen.getByRole('button', { name: /Goal.*\+1/i }));
    expect(screen.getByRole('button', { name: 'WHO SCORED?: Cam C' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    fireEvent.click(screen.getByRole('button', { name: /Game options/i }));
    fireEvent.click(screen.getByRole('button', { name: /Off roof/i }));
    expect(screen.getByLabelText('Responsible player')).toHaveDisplayValue('Alice A');
  });

  it('keeps common outcomes together and offers one-tap undo after saving', async () => {
    const point = { id: 'point-1', kind: 'observation', outcome: 'point', thrower_id: 'alice', recorded_by: 'me', sequence: 8 };
    mocks.getLiveGame
      .mockResolvedValueOnce(baseGame)
      .mockResolvedValueOnce({
        ...baseGame, score: [2, 1], version: 8,
        events: [point],
      })
      .mockResolvedValueOnce({ ...baseGame, version: 9, events: [] });
    mocks.sendLiveCommand
      .mockResolvedValueOnce({
        accepted_version: 8, first_sequence: 8, last_sequence: 8,
        projection: { score: [2, 1], status: 'active', coverage: 'complete' },
      })
      .mockResolvedValueOnce({
        accepted_version: 9, first_sequence: 9, last_sequence: 9,
        projection: { score: [1, 1], status: 'active', coverage: 'complete' },
      });
    renderGame();

    const controls = await screen.findByRole('region', { name: 'Live scoring controls' });
    const commonResults = within(controls).getAllByRole('button')
      .map((button) => button.textContent.trim())
      .filter((label) => ['Miss', 'Table hit', 'Point +1', 'FIFA +1'].includes(label));
    expect(commonResults).toEqual(['Point +1', 'Table hit', 'FIFA +1', 'Miss']);
    fireEvent.click(await screen.findByRole('button', { name: 'Point' }));
    await waitFor(() => expect(mocks.sendLiveCommand).toHaveBeenCalledTimes(1));
    expect(mocks.sendLiveCommand.mock.calls[0][2]).toMatchObject({
      kind: 'record_throw', expected_version: 7, thrower_id: 'alice', outcome: 'point',
    });
    expect(await screen.findByText('Alice A scored · 2–1')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Bea B' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.queryByText(/are you sure/i)).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole('button', { name: 'Undo' }));
    await waitFor(() => expect(mocks.sendLiveCommand).toHaveBeenCalledTimes(2));
    expect(mocks.sendLiveCommand.mock.calls[1][2]).toMatchObject({
      kind: 'undo_last', target_event_id: 'point-1', expected_version: 8,
    });
    expect(screen.queryByText(/recalculated without/i)).not.toBeInTheDocument();
  });

  it('derives the next round from recorded team pairs without blocking a manual override', async () => {
    mocks.getLiveGame.mockResolvedValue({
      ...baseGame,
      events: [
        { id: 'a1', kind: 'observation', outcome: 'miss', thrower_id: 'alice', throwing_team_id: 'blue', sequence: 1 },
        { id: 'b1', kind: 'observation', outcome: 'miss', thrower_id: 'bea', throwing_team_id: 'blue', sequence: 2 },
        { id: 'c1', kind: 'observation', outcome: 'miss', thrower_id: 'cam', throwing_team_id: 'clay', sequence: 3 },
        { id: 'd1', kind: 'observation', outcome: 'miss', thrower_id: 'dev', throwing_team_id: 'clay', sequence: 4 },
      ],
    });
    renderGame();

    expect(await screen.findByRole('button', { name: 'Alice A' })).toHaveAttribute('aria-pressed', 'true');
    fireEvent.click(screen.getByRole('button', { name: 'Cam C' }));
    expect(screen.getByRole('button', { name: 'Cam C' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('keeps advanced stat results reachable without slowing common scoring', async () => {
    mocks.getLiveGame.mockResolvedValue(baseGame);
    mocks.sendLiveCommand.mockResolvedValue({
      accepted_version: 8,
      projection: { score: [2, 1], status: 'active', coverage: 'complete' },
    });
    renderGame();
    fireEvent.click(await screen.findByRole('button', { name: /More results/i }));
    fireEvent.change(screen.getByLabelText('Result'), { target: { value: 'self_sink' } });
    fireEvent.click(screen.getByRole('button', { name: 'Record self sink' }));
    await waitFor(() => expect(mocks.sendLiveCommand).toHaveBeenCalledTimes(1));
    expect(mocks.sendLiveCommand.mock.calls[0][2]).toMatchObject({
      kind: 'record_throw', thrower_id: 'alice', outcome: 'self_sink', expected_version: 7,
    });
  });

  it('attributes advanced results to the selected player and shows that assignment', async () => {
    mocks.getLiveGame.mockResolvedValue(baseGame);
    mocks.sendLiveCommand.mockResolvedValue({
      accepted_version: 8,
      projection: { score: [1, 1], status: 'active', coverage: 'complete' },
    });
    renderGame();

    fireEvent.click(await screen.findByRole('button', { name: 'Cam C' }));
    fireEvent.click(screen.getByRole('button', { name: /More results/i }));
    const attribution = screen.getByLabelText('Advanced result attribution');
    expect(within(attribution).getByText('Cam C')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Record sink' }));

    await waitFor(() => expect(mocks.sendLiveCommand).toHaveBeenCalledTimes(1));
    expect(mocks.sendLiveCommand.mock.calls[0][2]).toMatchObject({
      kind: 'record_throw', thrower_id: 'cam', outcome: 'sink', expected_version: 7,
    });
  });

  it('records a FIFA catch by asking for the catcher and inferring their teammate as kicker', async () => {
    mocks.getLiveGame.mockResolvedValue(baseGame);
    mocks.sendLiveCommand.mockResolvedValue({
      accepted_version: 8,
      projection: { score: [2, 1], status: 'active', coverage: 'complete' },
    });
    renderGame();
    fireEvent.click(await screen.findByRole('button', { name: /FIFA/i }));
    expect(screen.getByRole('heading', { name: 'FIFA' })).toBeInTheDocument();
    expect(screen.queryByLabelText('Result')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /Catch.*\+1/i }));
    fireEvent.click(screen.getByRole('button', { name: 'WHO CAUGHT IT?: Cam C' }));
    await waitFor(() => expect(mocks.sendLiveCommand).toHaveBeenCalledTimes(1));
    expect(mocks.sendLiveCommand.mock.calls[0][2]).toMatchObject({
      kind: 'record_throw', thrower_id: 'alice', outcome: 'fifa',
      fifa: { finish: 'kick_catch', kicker_id: 'dev', catcher_id: 'cam' },
    });
  });

  it('keeps FIFA participants on the team opposing the selected thrower', async () => {
    mocks.getLiveGame.mockResolvedValue(baseGame);
    mocks.sendLiveCommand.mockResolvedValue({
      accepted_version: 8,
      projection: { score: [2, 1], status: 'active', coverage: 'complete' },
    });
    renderGame();
    fireEvent.click(await screen.findByRole('button', { name: 'Cam C' }));
    fireEvent.click(screen.getByRole('button', { name: /More results/i }));
    fireEvent.change(screen.getByLabelText('Result'), { target: { value: 'fifa' } });
    fireEvent.click(screen.getByRole('button', { name: /Catch.*\+1/i }));
    expect(screen.getByRole('button', { name: 'WHO CAUGHT IT?: Alice A' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'WHO CAUGHT IT?: Bea B' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'WHO CAUGHT IT?: Bea B' }));

    await waitFor(() => expect(mocks.sendLiveCommand).toHaveBeenCalledTimes(1));
    expect(mocks.sendLiveCommand.mock.calls[0][2]).toMatchObject({
      kind: 'record_throw', thrower_id: 'cam', outcome: 'fifa',
      fifa: { finish: 'kick_catch', kicker_id: 'alice', catcher_id: 'bea' },
    });
  });

  it('records a saved FIFA goal with its kicker and opposing saver and no client score', async () => {
    mocks.getLiveGame.mockResolvedValue(baseGame);
    mocks.sendLiveCommand.mockResolvedValue({
      accepted_version: 8,
      projection: { score: [1, 1], status: 'active', coverage: 'complete' },
    });
    renderGame();

    fireEvent.click(await screen.findByRole('button', { name: /FIFA/i }));
    fireEvent.click(screen.getByRole('button', { name: /Saved.*0/i }));
    fireEvent.click(screen.getByRole('button', { name: 'WHO KICKED IT?: Cam C' }));
    expect(screen.getByRole('button', { name: 'WHO SAVED IT?: Alice A' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'WHO SAVED IT?: Bea B' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'WHO SAVED IT?: Bea B' }));

    await waitFor(() => expect(mocks.sendLiveCommand).toHaveBeenCalledTimes(1));
    expect(mocks.sendLiveCommand.mock.calls[0][2]).toMatchObject({
      kind: 'record_throw', thrower_id: 'alice', outcome: 'fifa',
      fifa: { finish: 'goal_saved', kicker_id: 'cam', saver_id: 'bea' },
    });
    expect(mocks.sendLiveCommand.mock.calls[0][2]).not.toHaveProperty('score_delta');
    expect(await screen.findByText('Bea B saved the FIFA · 1–1')).toBeInTheDocument();
  });

  it('requires and records short/low characteristics for invalid throws', async () => {
    mocks.getLiveGame.mockResolvedValue(baseGame);
    mocks.sendLiveCommand.mockResolvedValue({
      accepted_version: 8,
      projection: { score: [1, 1], status: 'active', coverage: 'complete' },
    });
    renderGame();
    fireEvent.click(await screen.findByRole('button', { name: /More results/i }));
    fireEvent.change(screen.getByLabelText('Result'), { target: { value: 'invalid' } });
    const recordButton = screen.getByRole('button', { name: 'Record invalid' });
    expect(recordButton).toBeDisabled();
    fireEvent.click(screen.getByLabelText('short'));
    expect(recordButton).not.toBeDisabled();
    fireEvent.click(recordButton);
    await waitFor(() => expect(mocks.sendLiveCommand).toHaveBeenCalledTimes(1));
    expect(mocks.sendLiveCommand.mock.calls[0][2]).toMatchObject({
      kind: 'record_throw', outcome: 'invalid', characteristics: ['short'],
    });
  });

  it('does not let a cached reload replace a newer accepted server receipt', async () => {
    mocks.getLiveGame.mockResolvedValue(baseGame);
    mocks.sendLiveCommand.mockResolvedValue({
      accepted_version: 8,
      projection: { score: [2, 1], status: 'active', coverage: 'complete' },
    });
    renderGame();

    fireEvent.click(await screen.findByRole('button', { name: 'Point' }));
    expect(await screen.findByText('Alice A scored · 2–1')).toBeInTheDocument();
    expect(screen.getByText('2–1')).toBeInTheDocument();
  });

  it('shows recent server events and prevents scoring before joining', async () => {
    mocks.getLiveGame.mockResolvedValue({
      ...baseGame,
      referees: [],
      events: [{ id: 'e1', kind: 'observation', outcome: 'point', thrower_id: 'cam', sequence: 3 }],
    });
    renderGame();
    expect(await screen.findByText('point')).toBeInTheDocument();
    expect(within(screen.getByRole('region', { name: 'Recent plays' })).getByText('Cam')).toBeInTheDocument();
    expect(screen.getByText(/join from the live games list/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Point' })).not.toBeInTheDocument();
  });

  it('replaces a whole mistaken result atomically without calling it a retoss', async () => {
    const point = { id: 'point-1', kind: 'observation', outcome: 'point', thrower_id: 'alice', sequence: 1 };
    mocks.getLiveGame
      .mockResolvedValueOnce({ ...baseGame, events: [point] })
      .mockResolvedValueOnce({ ...baseGame, score: [0, 1], version: 8, events: [point] });
    mocks.sendLiveCommand.mockResolvedValue({
      accepted_version: 8, projection: { score: [0, 1], status: 'active', coverage: 'complete' },
    });
    renderGame();

    fireEvent.click(await screen.findByRole('button', { name: 'Fix this result' }));
    expect(screen.getByText(/Edit the call, or retoss if they’ll throw again./i)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Replacement result'), { target: { value: 'miss' } });
    fireEvent.click(screen.getByRole('button', { name: 'Change result' }));

    await waitFor(() => expect(mocks.sendLiveCommand).toHaveBeenCalledTimes(1));
    expect(mocks.sendLiveCommand.mock.calls[0][2]).toMatchObject({
      kind: 'change_throw', target_event_id: 'point-1', thrower_id: 'alice', outcome: 'miss',
    });
    expect(await screen.findByText('Changed point → miss · 0–1')).toBeInTheDocument();
  });

  it('keeps physical retoss distinct and links the next physical throw', async () => {
    const point = { id: 'point-1', kind: 'observation', outcome: 'point', thrower_id: 'alice', sequence: 1 };
    const decision = { id: 'retoss-1', kind: 'retoss_decision', thrower_id: 'alice', target_event_id: 'point-1', sequence: 2 };
    mocks.getLiveGame
      .mockResolvedValueOnce({ ...baseGame, events: [point] })
      .mockResolvedValueOnce({ ...baseGame, score: [0, 1], status: 'awaiting_replay', version: 8, events: [point, decision] })
      .mockResolvedValueOnce({ ...baseGame, score: [1, 1], version: 9, events: [point, decision] });
    mocks.sendLiveCommand
      .mockResolvedValueOnce({ accepted_version: 8, projection: { score: [0, 1], status: 'awaiting_replay', coverage: 'complete' } })
      .mockResolvedValueOnce({ accepted_version: 9, projection: { score: [1, 1], status: 'active', coverage: 'complete' } });
    renderGame();

    fireEvent.click(await screen.findByRole('button', { name: 'Fix this result' }));
    fireEvent.click(screen.getByRole('button', { name: 'Retoss — new physical throw' }));
    expect(screen.getByText(/The old throw won’t count. The next one will./i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Confirm new physical retoss' }));
    await waitFor(() => expect(mocks.getLiveGame).toHaveBeenCalledTimes(2));
    expect(screen.getByText('Retoss · old throw removed · 0–1')).toBeInTheDocument();
    expect(await screen.findByText('RETOSS')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Point' }));
    await waitFor(() => expect(mocks.sendLiveCommand).toHaveBeenCalledTimes(2));
    expect(mocks.sendLiveCommand.mock.calls[1][2]).toMatchObject({
      kind: 'record_throw', thrower_id: 'alice', replay_of: 'retoss-1', outcome: 'point', expected_version: 8,
    });
  });

  it('links an advanced result as the pending physical retoss replay', async () => {
    const point = { id: 'point-1', kind: 'observation', outcome: 'point', thrower_id: 'cam', sequence: 1 };
    const decision = { id: 'retoss-1', kind: 'retoss_decision', thrower_id: 'cam', target_event_id: 'point-1', sequence: 2 };
    mocks.getLiveGame.mockResolvedValue({ ...baseGame, status: 'awaiting_replay', events: [point, decision] });
    mocks.sendLiveCommand.mockResolvedValue({
      accepted_version: 8, projection: { score: [1, 1], status: 'active', coverage: 'complete' },
    });
    renderGame();

    fireEvent.click(await screen.findByRole('button', { name: /More results/i }));
    expect(within(screen.getByLabelText('Advanced result attribution')).getByText('Cam C')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Record sink' }));

    await waitFor(() => expect(mocks.sendLiveCommand).toHaveBeenCalledTimes(1));
    expect(mocks.sendLiveCommand.mock.calls[0][2]).toMatchObject({
      kind: 'record_throw', thrower_id: 'cam', replay_of: 'retoss-1', outcome: 'sink', expected_version: 7,
    });
  });

  it('does not offer generic undo for a latest retoss decision', async () => {
    const point = { id: 'point-1', kind: 'observation', outcome: 'point', thrower_id: 'alice', recorded_by: 'me', sequence: 1 };
    const decision = { id: 'retoss-1', kind: 'retoss_decision', thrower_id: 'alice', recorded_by: 'me', target_event_id: 'point-1', sequence: 2 };
    mocks.getLiveGame.mockResolvedValue({ ...baseGame, status: 'awaiting_replay', events: [point, decision] });
    renderGame();

    expect(await screen.findByText('RETOSS')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Undo my last result' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Point' })).toBeInTheDocument();
  });

  it('reviews only the active replacement for a corrected logical throw', async () => {
    const point = { id: 'point-1', kind: 'observation', outcome: 'point', thrower_id: 'alice', sequence: 1 };
    const correction = { id: 'correction-1', kind: 'correction', target_event_id: 'point-1', sequence: 2 };
    const replacement = { id: 'miss-1', kind: 'observation', outcome: 'miss', thrower_id: 'alice', replacement_for: 'point-1', sequence: 3 };
    mocks.getLiveGame.mockResolvedValue({ ...baseGame, events: [point, correction, replacement] });
    mocks.sendLiveCommand.mockResolvedValue({
      accepted_version: 8, projection: { score: [1, 1], status: 'active', coverage: 'complete' },
    });
    renderGame();

    expect(await screen.findAllByRole('button', { name: 'Fix this result' })).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'Fix this result' }));
    fireEvent.change(screen.getByLabelText('Replacement result'), { target: { value: 'caught' } });
    fireEvent.click(screen.getByRole('button', { name: 'Change result' }));

    await waitFor(() => expect(mocks.sendLiveCommand).toHaveBeenCalledTimes(1));
    expect(mocks.sendLiveCommand.mock.calls[0][2]).toMatchObject({ target_event_id: 'miss-1' });
  });

  it('shows corrected and retossed plays without exposing decision events', async () => {
    const corrected = { id: 'point-1', kind: 'observation', outcome: 'point', thrower_id: 'alice', sequence: 1 };
    const correction = { id: 'correction-1', kind: 'correction', target_event_id: 'point-1', sequence: 2 };
    const replacement = { id: 'miss-1', kind: 'observation', outcome: 'miss', thrower_id: 'alice', replacement_for: 'point-1', sequence: 3 };
    const retossed = { id: 'caught-1', kind: 'observation', outcome: 'caught', thrower_id: 'bea', sequence: 4 };
    const retoss = { id: 'retoss-1', kind: 'retoss_decision', target_event_id: 'caught-1', sequence: 5 };
    mocks.getLiveGame.mockResolvedValue({ ...baseGame, events: [corrected, correction, replacement, retossed, retoss] });
    renderGame();

    expect(await screen.findByText('Corrected')).toBeInTheDocument();
    expect(screen.getByText('Replacement')).toBeInTheDocument();
    expect(screen.getByText('Retossed')).toBeInTheDocument();
    expect(screen.queryByText(/retoss decision/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/throw #/i)).not.toBeInTheDocument();
  });

  it('requires named consequence confirmation before removing an entry', async () => {
    const point = { id: 'point-1', kind: 'observation', outcome: 'point', thrower_id: 'alice', sequence: 1 };
    mocks.getLiveGame.mockResolvedValue({ ...baseGame, events: [point] });
    renderGame();
    fireEvent.click(await screen.findByRole('button', { name: 'Fix this result' }));
    fireEvent.click(screen.getByRole('button', { name: 'Remove mistaken entry' }));
    expect(screen.getByText(/Remove Alice A’s point/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument();
    expect(mocks.sendLiveCommand).not.toHaveBeenCalled();
  });

  it('replaces attribution and outcome together in the same logical slot', async () => {
    const miss = { id: 'miss-1', kind: 'observation', outcome: 'miss', thrower_id: 'alice', sequence: 4 };
    mocks.getLiveGame
      .mockResolvedValueOnce({ ...baseGame, events: [miss] })
      .mockResolvedValueOnce({ ...baseGame, score: [1, 2], version: 8, events: [miss] });
    mocks.sendLiveCommand.mockResolvedValue({
      accepted_version: 8, projection: { score: [1, 2], status: 'active', coverage: 'complete' },
    });
    renderGame();
    fireEvent.click(await screen.findByRole('button', { name: 'Fix this result' }));
    fireEvent.change(screen.getByLabelText('Replacement thrower'), { target: { value: 'dev' } });
    fireEvent.change(screen.getByLabelText('Replacement result'), { target: { value: 'point' } });
    fireEvent.click(screen.getByRole('button', { name: 'Change result' }));

    await waitFor(() => expect(mocks.sendLiveCommand).toHaveBeenCalledTimes(1));
    expect(mocks.sendLiveCommand.mock.calls[0][2]).toMatchObject({
      kind: 'change_throw', target_event_id: 'miss-1', thrower_id: 'dev', outcome: 'point',
      reason: 'mistaken_entry', expected_version: 7,
    });
  });

  it('safe-cancels removal before a later explicit confirmation', async () => {
    const point = { id: 'point-1', kind: 'observation', outcome: 'point', thrower_id: 'alice', sequence: 1 };
    mocks.getLiveGame
      .mockResolvedValueOnce({ ...baseGame, events: [point] })
      .mockResolvedValueOnce({ ...baseGame, score: [0, 1], version: 8, events: [point] });
    mocks.sendLiveCommand.mockResolvedValue({
      accepted_version: 8, projection: { score: [0, 1], status: 'active', coverage: 'complete' },
    });
    renderGame();
    fireEvent.click(await screen.findByRole('button', { name: 'Fix this result' }));
    fireEvent.click(screen.getByRole('button', { name: 'Remove mistaken entry' }));
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(mocks.sendLiveCommand).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Remove mistaken entry' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Remove mistaken entry' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm remove mistaken entry' }));
    await waitFor(() => expect(mocks.sendLiveCommand).toHaveBeenCalledTimes(1));
    expect(mocks.sendLiveCommand.mock.calls[0][2]).toMatchObject({
      kind: 'remove_mistake', target_event_id: 'point-1', reason: 'mistaken_entry',
    });
  });

  it('fixes a known score with partial coverage without inventing throws', async () => {
    mocks.getLiveGame
      .mockResolvedValueOnce(baseGame)
      .mockResolvedValueOnce({ ...baseGame, score: [4, 3], version: 8, detail_coverage: 'partial' });
    mocks.sendLiveCommand.mockResolvedValue({ accepted_version: 8, projection: { score: [4, 3], status: 'active', coverage: 'partial' } });
    renderGame();
    fireEvent.click(await screen.findByRole('button', { name: 'Game options' }));
    fireEvent.click(screen.getByRole('button', { name: 'Catch up score' }));
    expect(screen.getByText(/Missed some plays\? Set the score and keep going./i)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Team 1 score'), { target: { value: '4' } });
    fireEvent.change(screen.getByLabelText('Team 2 score'), { target: { value: '3' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save known score' }));
    await waitFor(() => expect(mocks.sendLiveCommand).toHaveBeenCalledTimes(1));
    expect(mocks.sendLiveCommand.mock.calls[0][2]).toMatchObject({ kind: 'fix_score', score: [4, 3], coverage: 'partial' });
    expect(await screen.findByText('Score caught up · 4–3')).toBeInTheDocument();
  });

  it('treats the action sheet as a dismissible modal', async () => {
    mocks.getLiveGame.mockResolvedValue(baseGame);
    renderGame();
    fireEvent.click(await screen.findByRole('button', { name: 'Game options' }));
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveAttribute('aria-modal', 'true');
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Game options' }));
    fireEvent.click(screen.getByRole('button', { name: 'Close game actions' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('accepts unknown score coverage and leaves ordinary scoring available', async () => {
    mocks.getLiveGame
      .mockResolvedValueOnce({ ...baseGame, detail_coverage: 'unknown' })
      .mockResolvedValueOnce({ ...baseGame, score: [3, 2], version: 8, detail_coverage: 'unknown' });
    mocks.sendLiveCommand.mockResolvedValue({ accepted_version: 8, projection: { score: [3, 2], status: 'active', coverage: 'unknown' } });
    renderGame();
    fireEvent.click(await screen.findByRole('button', { name: 'Game options' }));
    fireEvent.click(screen.getByRole('button', { name: 'Catch up score' }));
    fireEvent.change(screen.getByLabelText('Team 1 score'), { target: { value: '3' } });
    fireEvent.change(screen.getByLabelText('Team 2 score'), { target: { value: '2' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save known score' }));
    await waitFor(() => expect(mocks.sendLiveCommand).toHaveBeenCalledTimes(1));
    expect(mocks.sendLiveCommand.mock.calls[0][2]).toMatchObject({ coverage: 'unknown' });
    expect(screen.getByRole('button', { name: 'Point' })).toBeInTheDocument();
  });

  it('shows ready to finish without auto-completing and permits incomplete finish', async () => {
    const ready = { ...baseGame, score: [5, 3], status: 'ready_to_finish', detail_coverage: 'partial' };
    mocks.getLiveGame
      .mockResolvedValueOnce(ready)
      .mockResolvedValueOnce({ ...ready, status: 'completed', version: 8 });
    mocks.sendLiveCommand.mockResolvedValue({ accepted_version: 8, projection: { score: [5, 3], status: 'completed', coverage: 'partial' } });
    renderGame();
    const button = await screen.findByRole('button', { name: 'Finish game' });
    expect(mocks.sendLiveCommand).not.toHaveBeenCalled();
    fireEvent.click(button);
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Finish game' }));
    expect(screen.getByText(/Finish at the score shown./i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Confirm finish at 5–3' }));
    await waitFor(() => expect(mocks.sendLiveCommand).toHaveBeenCalledTimes(1));
    expect(mocks.sendLiveCommand.mock.calls[0][2]).toMatchObject({ kind: 'finish', coverage: 'partial', termination_reason: 'target_reached' });
    expect(await screen.findByText('Final · 5–3')).toBeInTheDocument();
  });

  it('safeguards attributed off-roof completion and shows canonical 0–5 receipt', async () => {
    mocks.getLiveGame
      .mockResolvedValueOnce(baseGame)
      .mockResolvedValueOnce({ ...baseGame, score: [0, 5], status: 'completed', version: 8 });
    mocks.sendLiveCommand.mockResolvedValue({ accepted_version: 8, projection: { score: [0, 5], status: 'completed', coverage: 'complete', termination_reason: 'off_roof' } });
    renderGame();
    fireEvent.click(await screen.findByRole('button', { name: 'Game options' }));
    fireEvent.click(screen.getByRole('button', { name: 'Off roof · immediate 0–5 loss' }));
    fireEvent.change(screen.getByLabelText('Responsible player'), { target: { value: 'alice' } });
    fireEvent.click(screen.getByRole('button', { name: 'Review immediate loss' }));
    expect(screen.getByText(/confirm Alice A caused an off-roof 0–5 loss/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Confirm off-roof 0–5 completion' }));
    expect(await screen.findByText('Off roof · 0–5')).toBeInTheDocument();
    expect(screen.getByText('Final')).toBeInTheDocument();
  });

  it('retains stale intent, reloads canonical change, and requires explicit resubmit', async () => {
    const otherPoint = { id: 'other-1', kind: 'observation', outcome: 'point', thrower_id: 'cam', recorded_by: 'other-ref', sequence: 1 };
    mocks.getLiveGame
      .mockResolvedValueOnce(baseGame)
      .mockResolvedValueOnce({ ...baseGame, score: [1, 2], version: 8, events: [otherPoint] })
      .mockResolvedValueOnce({ ...baseGame, score: [2, 2], version: 9, events: [otherPoint] });
    mocks.sendLiveCommand
      .mockRejectedValueOnce({ status: 409, detail: { code: 'dice_live.stale_version', current_version: 8 }, message: 'stale' })
      .mockResolvedValueOnce({ accepted_version: 9, projection: { score: [2, 2], status: 'active', coverage: 'complete' } });
    renderGame();
    fireEvent.click(await screen.findByRole('button', { name: 'Point' }));
    expect(await screen.findByText(/another referee updated the game/i)).toBeInTheDocument();
    expect(screen.getByText(/Cam C · point was added/i)).toBeInTheDocument();
    expect(mocks.sendLiveCommand).toHaveBeenCalledTimes(1);
    const staleId = mocks.sendLiveCommand.mock.calls[0][2].client_command_id;
    fireEvent.click(screen.getByRole('button', { name: 'Save my result now' }));
    await waitFor(() => expect(mocks.sendLiveCommand).toHaveBeenCalledTimes(2));
    expect(mocks.sendLiveCommand.mock.calls[1][2]).toMatchObject({ expected_version: 8, outcome: 'point', thrower_id: 'alice' });
    expect(mocks.sendLiveCommand.mock.calls[1][2].client_command_id).not.toBe(staleId);
  });

  it('retries an ambiguous timeout with the exact same command ID', async () => {
    mocks.getLiveGame
      .mockResolvedValueOnce(baseGame)
      .mockResolvedValueOnce({ ...baseGame, score: [2, 1], version: 8 });
    mocks.sendLiveCommand
      .mockRejectedValueOnce(new Error('timeout'))
      .mockResolvedValueOnce({ accepted_version: 8, projection: { score: [2, 1], status: 'active', coverage: 'complete' } });
    renderGame();
    fireEvent.click(await screen.findByRole('button', { name: 'Point' }));
    expect(await screen.findByText(/Retrying will not create a duplicate/i)).toBeInTheDocument();
    const first = mocks.sendLiveCommand.mock.calls[0][2];
    fireEvent.click(screen.getByRole('button', { name: 'Try saving again' }));
    await waitFor(() => expect(mocks.sendLiveCommand).toHaveBeenCalledTimes(2));
    expect(mocks.sendLiveCommand.mock.calls[1][2]).toEqual(first);
  });

  it('safeguards append-only reopen and names its official target', async () => {
    const completion = { id: 'finish-1', kind: 'completion', recorded_by: 'me', sequence: 6 };
    const completed = { ...baseGame, score: [5, 3], status: 'completed', version: 8, detail_coverage: 'partial', events: [completion] };
    mocks.getLiveGame
      .mockResolvedValueOnce(completed)
      .mockResolvedValueOnce({ ...completed, status: 'active', version: 9 });
    mocks.sendLiveCommand.mockResolvedValue({ accepted_version: 9, projection: { score: [5, 3], status: 'active', coverage: 'partial' } });
    renderGame();
    fireEvent.click(await screen.findByRole('button', { name: 'Reopen game' }));
    expect(screen.getByText(/final result needs another correction/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Cancel — preserve current game' })).toBeInTheDocument();
    expect(mocks.sendLiveCommand).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Confirm reopen' }));
    await waitFor(() => expect(mocks.sendLiveCommand).toHaveBeenCalledTimes(1));
    expect(mocks.sendLiveCommand.mock.calls[0][2]).toMatchObject({ kind: 'reopen', target_event_id: 'finish-1', expected_version: 8 });
  });

  it('does not leave a second generic undo control in the referee flow', async () => {
    const own = { id: 'own-1', kind: 'observation', outcome: 'miss', thrower_id: 'alice', recorded_by: 'me', sequence: 2 };
    mocks.getLiveGame.mockResolvedValue({ ...baseGame, events: [own] });
    renderGame();
    await screen.findByText('1–1');
    expect(screen.queryByRole('button', { name: 'Undo my last result' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Fix this result' })).toBeInTheDocument();
  });

  it('does not offer generic undo for a latest score checkpoint', async () => {
    const checkpoint = { id: 'checkpoint-1', kind: 'score_checkpoint', score: [2, 1], coverage: 'partial', recorded_by: 'me', sequence: 3 };
    mocks.getLiveGame.mockResolvedValue({ ...baseGame, score: [2, 1], detail_coverage: 'partial', events: [checkpoint] });
    renderGame();

    expect(await screen.findByText('2–1')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Undo my last result' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Game options' }));
    expect(screen.getByRole('button', { name: 'Catch up score' })).toBeInTheDocument();
  });

  it('does not offer generic undo after another referee corrects the latest own observation', async () => {
    const own = { id: 'own-1', kind: 'observation', outcome: 'point', thrower_id: 'alice', recorded_by: 'me', sequence: 1 };
    const correction = { id: 'correction-1', kind: 'correction', target_event_id: 'own-1', recorded_by: 'other', sequence: 2 };
    const replacement = { id: 'replacement-1', kind: 'observation', outcome: 'miss', thrower_id: 'alice', replacement_for: 'own-1', recorded_by: 'other', sequence: 3 };
    mocks.getLiveGame.mockResolvedValue({ ...baseGame, events: [own, correction, replacement] });
    renderGame();

    expect(await screen.findByRole('button', { name: 'Fix this result' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Undo my last result' })).not.toBeInTheDocument();
  });

  it('does not offer generic undo beneath another referee retoss decision', async () => {
    const own = { id: 'own-1', kind: 'observation', outcome: 'point', thrower_id: 'alice', recorded_by: 'me', sequence: 1 };
    const decision = { id: 'retoss-1', kind: 'retoss_decision', thrower_id: 'alice', target_event_id: 'own-1', recorded_by: 'other', sequence: 2 };
    mocks.getLiveGame.mockResolvedValue({ ...baseGame, status: 'awaiting_replay', events: [own, decision] });
    renderGame();

    expect(await screen.findByText('RETOSS')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Undo my last result' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Point' })).toBeInTheDocument();
  });

  it('discards retained stale intent without resubmitting it', async () => {
    mocks.getLiveGame
      .mockResolvedValueOnce(baseGame)
      .mockResolvedValueOnce({ ...baseGame, score: [1, 2], version: 8, events: [] });
    mocks.sendLiveCommand.mockRejectedValue({ status: 409, detail: { code: 'dice_live.stale_version' }, message: 'stale' });
    renderGame();
    fireEvent.click(await screen.findByRole('button', { name: 'Point' }));
    expect(await screen.findByLabelText('Unsaved referee intent')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Discard unsaved intent' }));
    expect(screen.queryByLabelText('Unsaved referee intent')).not.toBeInTheDocument();
    expect(mocks.sendLiveCommand).toHaveBeenCalledTimes(1);
  });

  it('fails closed immediately when the effective flag turns off after loading', async () => {
    mocks.getLiveGame.mockResolvedValue(baseGame);
    const enabledAuth = { token: 'token', user: { id: 'me' }, features: { dice_live_referee: { opted_in: true, effective: true } } };
    const disabledAuth = { ...enabledAuth, features: { dice_live_referee: { opted_in: true, effective: false } } };
    const view = render(
      <MemoryRouter initialEntries={['/dice/live/match-1']}>
        <Routes><Route path="/dice/live/:matchId" element={<LiveGame auth={enabledAuth} />} /></Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText('1–1')).toBeInTheDocument();
    view.rerender(
      <MemoryRouter initialEntries={['/dice/live/match-1']}>
        <Routes><Route path="/dice/live/:matchId" element={<LiveGame auth={disabledAuth} />} /></Routes>
      </MemoryRouter>,
    );
    expect(screen.getByText('Live referee unavailable')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Reload' })).not.toBeInTheDocument();
    expect(mocks.getLiveGame).toHaveBeenCalledTimes(1);
  });
});
