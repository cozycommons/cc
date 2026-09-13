import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useNavigate } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  getLiveGame: vi.fn(), getLivePrediction: vi.fn(), getLivePulse: vi.fn(),
  sendLiveCommand: vi.fn(), updateLiveSettings: vi.fn(),
}));
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
const enabledAuth = { token: 'token', user: { id: 'me' }, features: { dice_live_referee: { opted_in: true, effective: true } } };

function renderGame({ effective = true } = {}) {
  const auth = { ...enabledAuth, features: { dice_live_referee: { opted_in: effective, effective } } };
  return render(
    <MemoryRouter initialEntries={['/dice/live/match-1']}>
      <Routes><Route path="/dice/live/:matchId" element={<LiveGame auth={auth} />} /></Routes>
    </MemoryRouter>,
  );
}

const renderRouteSwitch = () => render(
  <MemoryRouter initialEntries={['/dice/live/match-1']}><RouteSwitch auth={enabledAuth} /></MemoryRouter>,
);

function RouteSwitch({ auth }) {
  const navigate = useNavigate();
  return <>
    <button type="button" onClick={() => navigate('/dice/live/match-1')}>Open match 1</button>
    <button type="button" onClick={() => navigate('/dice/live/match-2')}>Open match 2</button>
    <Routes><Route path="/dice/live/:matchId" element={<LiveGame auth={auth} />} /></Routes>
  </>;
}

describe('LiveGame common scoring', () => {
  afterEach(() => {
    vi.useRealTimers();
    window.localStorage.clear();
    vi.resetAllMocks();
  });

  it('ignores a stale opt-out and requests the released live game', async () => {
    mocks.getLiveGame.mockResolvedValue(baseGame);
    renderGame({ effective: false });
    expect(await screen.findByText('1–1')).toBeInTheDocument();
    expect(mocks.getLiveGame).toHaveBeenCalled();
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
    expect(within(summary).getByLabelText('2 points')).toBeInTheDocument();
    expect(within(summary).getByLabelText('1 sink')).toBeInTheDocument();
    expect(within(summary).getByLabelText('1 self-sink')).toBeInTheDocument();
    expect(within(summary).getByLabelText('1 FIFA allowed')).toBeInTheDocument();
    expect(within(summary).getByLabelText('1 FIFA goal')).toBeInTheDocument();
    expect(within(summary).getByLabelText('2 FIFA kicks')).toBeInTheDocument();
    expect(within(summary).getByLabelText('1 FIFA catch')).toBeInTheDocument();
    expect(within(summary).getByLabelText('1 FIFA save')).toBeInTheDocument();
    expect(within(summary).getByText('Missing plays are excluded, not counted as misses.')).toBeInTheDocument();
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

  it('requires a referee to establish the thrower after a score gap', async () => {
    mocks.getLiveGame.mockResolvedValue({
      ...baseGame,
      detail_coverage: 'partial',
      events: [
        { id: 'a1', kind: 'observation', outcome: 'miss', thrower_id: 'alice', throwing_team_id: 'blue', sequence: 1 },
        { id: 'gap', kind: 'score_checkpoint', score: [2, 1], coverage: 'partial', sequence: 2 },
      ],
    });
    renderGame();

    expect(await screen.findByText('Order unknown · choose thrower')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Point' })).toBeDisabled();
    for (const name of ['Alice A', 'Bea B', 'Cam C', 'Dev D']) {
      expect(screen.getByRole('button', { name })).toHaveAttribute('aria-pressed', 'false');
    }
    fireEvent.click(screen.getByRole('button', { name: 'Cam C' }));
    expect(screen.getByRole('button', { name: 'Cam C' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Point' })).toBeEnabled();
  });

  it('coalesces foreground resync while a canonical refresh is in flight', async () => {
    let finishRefresh;
    mocks.getLiveGame
      .mockResolvedValueOnce(baseGame)
      .mockImplementationOnce(() => new Promise((resolve) => { finishRefresh = resolve; }));
    renderGame();
    await screen.findByText('1–1');

    fireEvent(window, new Event('focus'));
    await waitFor(() => expect(mocks.getLiveGame).toHaveBeenCalledTimes(2));
    fireEvent(document, new Event('visibilitychange'));
    expect(mocks.getLiveGame).toHaveBeenCalledTimes(2);
    finishRefresh(baseGame);
    await waitFor(() => expect(mocks.getLiveGame).toHaveBeenCalledTimes(2));
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

  it('records who caught an ordinary table hit', async () => {
    mocks.getLiveGame.mockResolvedValue(baseGame);
    mocks.sendLiveCommand.mockResolvedValue({
      accepted_version: 8,
      projection: { score: [1, 1], status: 'active', coverage: 'complete' },
    });
    renderGame();

    fireEvent.click(await screen.findByRole('button', { name: 'Table hit' }));
    expect(screen.getByRole('heading', { name: 'Table hit' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'WHO CAUGHT IT?: Alice A' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'WHO CAUGHT IT?: Cam C' }));

    await waitFor(() => expect(mocks.sendLiveCommand).toHaveBeenCalledTimes(1));
    expect(mocks.sendLiveCommand.mock.calls[0][2]).toMatchObject({
      kind: 'record_throw', thrower_id: 'alice', outcome: 'caught', catcher_id: 'cam', expected_version: 7,
    });
    expect(await screen.findByText('Cam C caught Alice A’s table hit · 1–1')).toBeInTheDocument();
  });

  it('records an uncaught table hit without awarding a point or inventing a catcher', async () => {
    mocks.getLiveGame.mockResolvedValue(baseGame);
    mocks.sendLiveCommand.mockResolvedValue({
      accepted_version: 8,
      projection: { score: [1, 1], status: 'active', coverage: 'complete' },
    });
    renderGame();

    fireEvent.click(await screen.findByRole('button', { name: 'Table hit' }));
    fireEvent.click(screen.getByRole('button', { name: 'WHO CAUGHT IT?: Dead — no one caught it' }));

    await waitFor(() => expect(mocks.sendLiveCommand).toHaveBeenCalledTimes(1));
    expect(mocks.sendLiveCommand.mock.calls[0][2]).toMatchObject({
      kind: 'record_throw', thrower_id: 'alice', outcome: 'caught', expected_version: 7,
    });
    expect(mocks.sendLiveCommand.mock.calls[0][2]).not.toHaveProperty('catcher_id');
    expect(await screen.findByText('Alice A hit the table · no catch · 1–1')).toBeInTheDocument();
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

  it('locks stale event actions after a saved command until canonical history refreshes', async () => {
    const earlierPoint = { id: 'point-1', kind: 'observation', outcome: 'point', thrower_id: 'alice', sequence: 1 };
    const savedPoint = { id: 'point-2', kind: 'observation', outcome: 'point', thrower_id: 'bea', sequence: 2 };
    mocks.getLiveGame
      .mockResolvedValueOnce({ ...baseGame, events: [earlierPoint] })
      .mockRejectedValueOnce(new Error('connection lost'))
      .mockResolvedValue({ ...baseGame, score: [2, 1], version: 8, events: [earlierPoint, savedPoint] });
    mocks.sendLiveCommand.mockResolvedValue({
      accepted_version: 8, last_sequence: 2,
      projection: { score: [2, 1], status: 'active', coverage: 'complete' },
    });
    renderGame();

    fireEvent.click(await screen.findByRole('button', { name: 'Point' }));
    const pending = await screen.findByRole('region', { name: 'Refreshing saved result' });
    expect(within(pending).getByRole('status')).toHaveTextContent(/Refreshing official history/i);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Point' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Fix this result' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Game options' })).toBeDisabled();
    expect(screen.getByRole('radio', { name: 'Ranked — Affects ELO' })).toBeDisabled();

    fireEvent.click(within(pending).getByRole('button', { name: 'Refresh now' }));
    await waitFor(() => expect(screen.queryByRole('region', { name: 'Refreshing saved result' })).not.toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Point' })).toBeEnabled();
    expect(mocks.getLiveGame.mock.calls.length).toBeGreaterThanOrEqual(3);
  });

  it('keeps the saved-result lock across reload until the accepted version is visible', async () => {
    const earlierPoint = { id: 'point-1', kind: 'observation', outcome: 'point', thrower_id: 'alice', sequence: 1 };
    const canonical = { ...baseGame, events: [earlierPoint] };
    mocks.getLiveGame.mockResolvedValueOnce(canonical).mockResolvedValueOnce(canonical);
    mocks.sendLiveCommand.mockResolvedValue({
      accepted_version: 8, last_sequence: 2,
      projection: { score: [2, 1], status: 'active', coverage: 'complete' },
    });
    const firstView = renderGame();
    fireEvent.click(await screen.findByRole('button', { name: 'Point' }));
    await screen.findByRole('region', { name: 'Refreshing saved result' });
    firstView.unmount();

    mocks.getLiveGame
      .mockResolvedValueOnce(canonical)
      .mockResolvedValue({ ...canonical, score: [2, 1], version: 8 });
    renderGame();
    const pending = await screen.findByRole('region', { name: 'Refreshing saved result' });
    expect(screen.getByRole('button', { name: 'Point' })).toBeDisabled();
    fireEvent.click(within(pending).getByRole('button', { name: 'Refresh now' }));
    await waitFor(() => expect(screen.queryByRole('region', { name: 'Refreshing saved result' })).not.toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Point' })).toBeEnabled();
    expect(window.localStorage.length).toBe(0);
  });

  it('does not unlock when another tab has recorded a newer canonical version', async () => {
    let resolveInitial;
    window.localStorage.setItem('dice.live-canonical.v1:me:match-1:8', '1');
    mocks.getLiveGame
      .mockImplementationOnce(() => new Promise((resolve) => { resolveInitial = resolve; }))
      .mockResolvedValue({ ...baseGame, version: 9 });
    renderGame();
    await waitFor(() => expect(mocks.getLiveGame).toHaveBeenCalledTimes(1));
    window.localStorage.setItem('dice.live-canonical.v1:me:match-1:9', '1');
    await act(async () => resolveInitial({ ...baseGame, version: 8 }));

    const pending = await screen.findByRole('region', { name: 'Refreshing saved result' });
    expect(screen.getByRole('button', { name: 'Point' })).toBeDisabled();
    fireEvent.click(within(pending).getByRole('button', { name: 'Refresh now' }));
    await waitFor(() => expect(screen.queryByRole('region', { name: 'Refreshing saved result' })).not.toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Point' })).toBeEnabled();
  });

  it('locks when another tab records a newer canonical requirement after load', async () => {
    mocks.getLiveGame.mockResolvedValue(baseGame);
    renderGame();
    expect(await screen.findByText('1–1')).toBeInTheDocument();
    act(() => {
      window.localStorage.setItem('dice.live-canonical.v1:me:match-1:8', '1');
      window.dispatchEvent(new StorageEvent('storage', {
        key: 'dice.live-canonical.v1:me:match-1:8', newValue: '1',
      }));
    });

    expect(await screen.findByRole('region', { name: 'Refreshing saved result' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Point' })).toBeDisabled();
  });

  it('scopes a pending canonical version to its user and match', async () => {
    mocks.getLiveGame.mockImplementation((_token, matchId) => Promise.resolve(
      matchId === 'match-2' ? { ...baseGame, id: 'match-2', score: [0, 0], version: 1 } : baseGame,
    ));
    mocks.sendLiveCommand.mockResolvedValue({
      accepted_version: 8,
      projection: { score: [2, 1], status: 'active', coverage: 'complete' },
    });
    renderRouteSwitch();
    fireEvent.click(await screen.findByRole('button', { name: 'Point' }));
    await screen.findByRole('region', { name: 'Refreshing saved result' });

    fireEvent.click(screen.getByRole('button', { name: 'Open match 2' }));
    expect(await screen.findByText('0–0')).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Refreshing saved result' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Point' })).toBeEnabled();
  });

  it('ignores an accepted command response after navigating to another match', async () => {
    let accept;
    mocks.getLiveGame.mockImplementation((_token, matchId) => Promise.resolve(
      matchId === 'match-2' ? { ...baseGame, id: 'match-2', score: [0, 0], version: 1 } : baseGame,
    ));
    mocks.sendLiveCommand.mockImplementation(() => new Promise((resolve) => { accept = resolve; }));
    renderRouteSwitch();
    fireEvent.click(await screen.findByRole('button', { name: 'Point' }));
    await screen.findByText(/Saving this result/i);

    fireEvent.click(screen.getByRole('button', { name: 'Open match 2' }));
    expect(await screen.findByText('0–0')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Point' })).toBeEnabled();
    await act(async () => accept({
      accepted_version: 8,
      projection: { score: [2, 1], status: 'active', coverage: 'complete' },
    }));
    expect(screen.getByText('0–0')).toBeInTheDocument();
    expect(screen.queryByText('2–1')).not.toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Refreshing saved result' })).not.toBeInTheDocument();
  });

  it('does not carry ambiguous recovery actions into another match', async () => {
    mocks.getLiveGame.mockImplementation((_token, matchId) => Promise.resolve(
      matchId === 'match-2' ? { ...baseGame, id: 'match-2', score: [0, 0], version: 1 } : baseGame,
    ));
    mocks.sendLiveCommand.mockRejectedValue(new Error('connection lost'));
    renderRouteSwitch();
    fireEvent.click(await screen.findByRole('button', { name: 'Point' }));
    await screen.findByRole('region', { name: 'Unsaved referee intent' });

    fireEvent.click(screen.getByRole('button', { name: 'Open match 2' }));
    expect(await screen.findByText('0–0')).toBeInTheDocument();
    expect(screen.queryByRole('region', { name: 'Unsaved referee intent' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Point' })).toBeEnabled();
  });

  it('does not surface a failed stale-version refresh in another match', async () => {
    let rejectRefresh;
    mocks.getLiveGame
      .mockResolvedValueOnce(baseGame)
      .mockImplementationOnce(() => new Promise((_resolve, reject) => { rejectRefresh = reject; }))
      .mockImplementation((_token, matchId) => Promise.resolve({ ...baseGame, id: matchId, score: [0, 0], version: 1 }));
    mocks.sendLiveCommand.mockRejectedValue({ status: 409, detail: { code: 'dice_live.stale_version' } });
    renderRouteSwitch();
    fireEvent.click(await screen.findByRole('button', { name: 'Point' }));
    await waitFor(() => expect(mocks.getLiveGame).toHaveBeenCalledTimes(2));

    fireEvent.click(screen.getByRole('button', { name: 'Open match 2' }));
    expect(await screen.findByText('0–0')).toBeInTheDocument();
    await act(async () => rejectRefresh(new Error('connection lost')));
    expect(screen.queryByRole('region', { name: 'Unsaved referee intent' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Point' })).toBeEnabled();
  });

  it('locks and scopes ranked-setting requests', async () => {
    let acceptSetting;
    mocks.getLiveGame.mockImplementation((_token, matchId) => Promise.resolve(
      matchId === 'match-2' ? { ...baseGame, id: 'match-2', score: [0, 0], version: 1, ranked: false } : { ...baseGame, ranked: false },
    ));
    mocks.updateLiveSettings.mockImplementation(() => new Promise((resolve) => { acceptSetting = resolve; }));
    renderRouteSwitch();
    const ranked = await screen.findByRole('radio', { name: 'Ranked — Affects ELO' });
    fireEvent.click(ranked);
    expect(ranked).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Point' })).toBeDisabled();

    fireEvent.click(screen.getByRole('button', { name: 'Open match 2' }));
    const matchTwoRanked = await screen.findByRole('radio', { name: 'Ranked — Affects ELO' });
    expect(matchTwoRanked).not.toBeChecked();
    fireEvent.click(screen.getByRole('button', { name: 'Open match 1' }));
    const returnedRanked = await screen.findByRole('radio', { name: 'Ranked — Affects ELO' });
    expect(returnedRanked).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Point' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Open match 2' }));
    await screen.findByText('0–0');
    await act(async () => acceptSetting({ ranked: true }));
    const currentRanked = screen.getByRole('radio', { name: 'Ranked — Affects ELO' });
    expect(currentRanked).not.toBeChecked();
    expect(currentRanked).toBeEnabled();
  });

  it('does not let an older load undo a saved ranked setting', async () => {
    let resolveOld;
    mocks.getLiveGame
      .mockResolvedValueOnce({ ...baseGame, ranked: false })
      .mockImplementationOnce(() => new Promise((resolve) => { resolveOld = resolve; }))
      .mockResolvedValueOnce({ ...baseGame, ranked: true });
    mocks.updateLiveSettings.mockResolvedValue({ ranked: true });
    renderGame();
    const ranked = await screen.findByRole('radio', { name: 'Ranked — Affects ELO' });
    fireEvent.click(screen.getByRole('button', { name: 'Reload' }));
    fireEvent.click(ranked);
    await waitFor(() => expect(ranked).toBeChecked());
    await waitFor(() => expect(mocks.getLiveGame).toHaveBeenCalledTimes(3));
    await act(async () => resolveOld({ ...baseGame, ranked: false }));
    expect(ranked).toBeChecked();
  });

  it('ignores an accepted command from a prior visit to the same match', async () => {
    let acceptCommand;
    let resolveReturn;
    mocks.getLiveGame
      .mockResolvedValueOnce(baseGame)
      .mockResolvedValueOnce({ ...baseGame, id: 'match-2', score: [0, 0], version: 1 })
      .mockImplementationOnce(() => new Promise((resolve) => { resolveReturn = resolve; }));
    mocks.sendLiveCommand.mockImplementation(() => new Promise((resolve) => { acceptCommand = resolve; }));
    renderRouteSwitch();
    fireEvent.click(await screen.findByRole('button', { name: 'Point' }));
    fireEvent.click(screen.getByRole('button', { name: 'Open match 2' }));
    await screen.findByText('0–0');
    fireEvent.click(screen.getByRole('button', { name: 'Open match 1' }));
    await waitFor(() => expect(mocks.getLiveGame).toHaveBeenCalledTimes(3));
    await act(async () => acceptCommand({
      accepted_version: 8, projection: { score: [2, 1], status: 'active', coverage: 'complete' },
    }));
    expect(screen.queryByText('2–1')).not.toBeInTheDocument();
    await act(async () => resolveReturn({ ...baseGame, score: [2, 1], version: 8 }));
    expect(await screen.findByText('2–1')).toBeInTheDocument();
  });

  it('does not crash when a ranked save returns during a new visit', async () => {
    let acceptSetting;
    let resolveReturn;
    mocks.getLiveGame
      .mockResolvedValueOnce({ ...baseGame, ranked: false })
      .mockResolvedValueOnce({ ...baseGame, id: 'match-2', score: [0, 0], version: 1, ranked: false })
      .mockImplementationOnce(() => new Promise((resolve) => { resolveReturn = resolve; }));
    mocks.updateLiveSettings.mockImplementation(() => new Promise((resolve) => { acceptSetting = resolve; }));
    renderRouteSwitch();
    fireEvent.click(await screen.findByRole('radio', { name: 'Ranked — Affects ELO' }));
    fireEvent.click(screen.getByRole('button', { name: 'Open match 2' }));
    await screen.findByText('0–0');
    fireEvent.click(screen.getByRole('button', { name: 'Open match 1' }));
    await waitFor(() => expect(mocks.getLiveGame).toHaveBeenCalledTimes(3));
    await act(async () => acceptSetting({ ranked: true }));
    expect(screen.queryByText('0–0')).not.toBeInTheDocument();
    await act(async () => resolveReturn({ ...baseGame, ranked: true }));
    expect(await screen.findByText('1–1')).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'Ranked — Affects ELO' })).toBeChecked();
  });

  it('shows manual reload progress and completion', async () => {
    let resolveReload;
    mocks.getLiveGame
      .mockResolvedValueOnce(baseGame)
      .mockImplementationOnce(() => new Promise((resolve) => { resolveReload = resolve; }));
    renderGame();
    fireEvent.click(await screen.findByRole('button', { name: 'Reload' }));
    expect(screen.getByRole('button', { name: 'Refreshing…' })).toBeDisabled();
    await act(async () => resolveReload({ ...baseGame, version: 8 }));
    expect(await screen.findByText('Official game refreshed.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reload' })).toBeEnabled();
  });

  it('reports a failed manual canonical refresh without releasing the saved-result lock', async () => {
    window.localStorage.setItem('dice.live-canonical.v1:me:match-1:8', '1');
    mocks.getLiveGame.mockResolvedValueOnce(baseGame).mockRejectedValueOnce(new Error('connection lost'));
    renderGame();
    const pending = await screen.findByRole('region', { name: 'Refreshing saved result' });
    fireEvent.click(within(pending).getByRole('button', { name: 'Refresh now' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Official game could not refresh. Try again.');
    expect(screen.getByRole('region', { name: 'Refreshing saved result' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Point' })).toBeDisabled();
    expect(within(pending).getByRole('button', { name: 'Refresh now' })).toBeEnabled();
  });

  it('offers reload when a persisted canonical requirement meets an initial load failure', async () => {
    window.localStorage.setItem('dice.live-canonical.v1:me:match-1:8', '1');
    mocks.getLiveGame
      .mockRejectedValueOnce(new Error('connection lost'))
      .mockResolvedValue({ ...baseGame, version: 8 });
    renderGame();
    expect(await screen.findByRole('alert')).toHaveTextContent('connection lost');

    fireEvent.click(screen.getByRole('button', { name: 'Reload' }));
    expect(await screen.findByText('1–1')).toBeInTheDocument();
    expect(screen.getByText('Official game refreshed.')).toBeInTheDocument();
  });

  it('does not retry retained intent through a newer cross-tab canonical lock', async () => {
    mocks.getLiveGame.mockResolvedValue(baseGame);
    mocks.sendLiveCommand.mockRejectedValue(new Error('connection lost'));
    renderGame();
    fireEvent.click(await screen.findByRole('button', { name: 'Point' }));
    const retry = await screen.findByRole('button', { name: 'Try saving again' });
    expect(retry).toBeEnabled();
    act(() => {
      window.localStorage.setItem('dice.live-canonical.v1:me:match-1:8', '1');
      window.dispatchEvent(new StorageEvent('storage', {
        key: 'dice.live-canonical.v1:me:match-1:8', newValue: '1',
      }));
    });

    expect(retry).toBeDisabled();
    act(() => window.dispatchEvent(new Event('online')));
    await waitFor(() => expect(mocks.getLiveGame).toHaveBeenCalledTimes(2));
    expect(mocks.sendLiveCommand).toHaveBeenCalledTimes(1);
  });

  it('does not start a canonical command refresh after the page unmounts', async () => {
    let acceptCommand;
    mocks.getLiveGame.mockResolvedValue(baseGame);
    mocks.sendLiveCommand.mockImplementation(() => new Promise((resolve) => { acceptCommand = resolve; }));
    const view = renderGame();
    fireEvent.click(await screen.findByRole('button', { name: 'Point' }));
    view.unmount();
    await act(async () => acceptCommand({
      accepted_version: 8, projection: { score: [2, 1], status: 'active', coverage: 'complete' },
    }));
    expect(mocks.getLiveGame).toHaveBeenCalledTimes(1);
  });

  it('does not start a canonical settings refresh after the page unmounts', async () => {
    let acceptSetting;
    mocks.getLiveGame.mockResolvedValue({ ...baseGame, ranked: false });
    mocks.updateLiveSettings.mockImplementation(() => new Promise((resolve) => { acceptSetting = resolve; }));
    const view = renderGame();
    fireEvent.click(await screen.findByRole('radio', { name: 'Ranked — Affects ELO' }));
    view.unmount();
    await act(async () => acceptSetting({ ranked: true }));
    expect(mocks.getLiveGame).toHaveBeenCalledTimes(1);
  });

  it('confirms completed-game rating recalculation after changing ranked', async () => {
    const completed = { ...baseGame, status: 'completed', ranked: false };
    mocks.getLiveGame.mockResolvedValueOnce(completed).mockResolvedValue({ ...completed, ranked: true });
    mocks.updateLiveSettings.mockResolvedValue({ ranked: true });
    renderGame();
    fireEvent.click(await screen.findByRole('radio', { name: 'Ranked — Affects ELO' }));
    expect(await screen.findByText('Ranked saved · ratings recalculated.')).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'Ranked — Affects ELO' })).toBeChecked();
    expect(mocks.getLiveGame).toHaveBeenCalledTimes(2);
  });

  it('shows recent server events and prevents scoring before joining', async () => {
    mocks.getLiveGame.mockResolvedValue({
      ...baseGame,
      referees: [],
      events: [{ id: 'e1', kind: 'observation', outcome: 'point', thrower_id: 'cam', sequence: 3 }],
    });
    renderGame();
    expect(await screen.findByText('Cam · point')).toBeInTheDocument();
    expect(screen.getByText(/join from the live games list/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Point' })).not.toBeInTheDocument();
  });

  it('keeps the play log compact while preserving table-hit and FIFA attribution', async () => {
    mocks.getLiveGame.mockResolvedValue({
      ...baseGame,
      events: [
        { id: 'dead', kind: 'observation', outcome: 'caught', thrower_id: 'alice', sequence: 1 },
        { id: 'caught', kind: 'observation', outcome: 'caught', thrower_id: 'alice', catcher_id: 'cam', sequence: 2 },
        { id: 'goal', kind: 'observation', outcome: 'fifa', thrower_id: 'bea', fifa: { finish: 'goal', kicker_id: 'dev' }, sequence: 3 },
        { id: 'fifa-catch', kind: 'observation', outcome: 'fifa', thrower_id: 'bea', fifa: { finish: 'kick_catch', kicker_id: 'dev', catcher_id: 'cam' }, sequence: 4 },
        { id: 'saved', kind: 'observation', outcome: 'fifa', thrower_id: 'alice', fifa: { finish: 'goal_saved', kicker_id: 'cam', saver_id: 'bea' }, sequence: 5 },
      ],
    });
    renderGame();

    const log = await screen.findByRole('region', { name: 'Recent plays' });
    expect(within(log).getAllByRole('listitem')).toHaveLength(5);
    expect(within(log).getAllByText('Alice · Table hit')).toHaveLength(2);
    expect(within(log).getByText('Dead · no catch')).toBeInTheDocument();
    expect(within(log).getByText('Caught by Cam')).toBeInTheDocument();
    expect(within(log).getByText('Dev scored')).toBeInTheDocument();
    expect(within(log).getByText('Dev → Cam')).toBeInTheDocument();
    expect(within(log).getByText('Cam → Bea saved')).toBeInTheDocument();
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
    expect(await screen.findByText('Retoss · old throw removed · 0–1')).toBeInTheDocument();
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
    fireEvent.click(screen.getByRole('button', { name: 'WHO CAUGHT IT?: Cam C' }));
    fireEvent.click(screen.getByRole('button', { name: 'Change result' }));

    await waitFor(() => expect(mocks.sendLiveCommand).toHaveBeenCalledTimes(1));
    expect(mocks.sendLiveCommand.mock.calls[0][2]).toMatchObject({ target_event_id: 'miss-1', catcher_id: 'cam' });
  });

  it('can correct a result to an uncaught table hit', async () => {
    const point = { id: 'point-1', kind: 'observation', outcome: 'point', thrower_id: 'alice', sequence: 1 };
    mocks.getLiveGame.mockResolvedValue({ ...baseGame, events: [point] });
    mocks.sendLiveCommand.mockResolvedValue({
      accepted_version: 8, projection: { score: [1, 1], status: 'active', coverage: 'complete' },
    });
    renderGame();

    fireEvent.click(await screen.findByRole('button', { name: 'Fix this result' }));
    fireEvent.change(screen.getByLabelText('Replacement result'), { target: { value: 'caught' } });
    fireEvent.click(screen.getByRole('button', { name: 'WHO CAUGHT IT?: Dead — no one caught it' }));
    fireEvent.click(screen.getByRole('button', { name: 'Change result' }));

    await waitFor(() => expect(mocks.sendLiveCommand).toHaveBeenCalledTimes(1));
    expect(mocks.sendLiveCommand.mock.calls[0][2]).toMatchObject({
      kind: 'change_throw', target_event_id: 'point-1', outcome: 'caught',
    });
    expect(mocks.sendLiveCommand.mock.calls[0][2]).not.toHaveProperty('catcher_id');
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

  it('retries the retained envelope when the phone returns online', async () => {
    mocks.getLiveGame.mockResolvedValue(baseGame);
    mocks.sendLiveCommand
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce({ accepted_version: 8, projection: { score: [2, 1], status: 'active', coverage: 'complete' } });
    renderGame();
    fireEvent.click(await screen.findByRole('button', { name: 'Point' }));
    await screen.findByText(/Retrying will not create a duplicate/i);
    const first = mocks.sendLiveCommand.mock.calls[0][2];

    act(() => window.dispatchEvent(new Event('online')));
    await waitFor(() => expect(mocks.sendLiveCommand).toHaveBeenCalledTimes(2));
    expect(mocks.sendLiveCommand.mock.calls[1][2]).toEqual(first);
  });

  it('shows an immediate pending state and permits only one in-flight command', async () => {
    let settle;
    mocks.getLiveGame.mockResolvedValue(baseGame);
    mocks.sendLiveCommand.mockImplementation(() => new Promise((resolve) => { settle = resolve; }));
    renderGame();

    const point = await screen.findByRole('button', { name: 'Point' });
    fireEvent.click(point);
    expect(await screen.findByRole('status')).toHaveTextContent('Saving this result');
    expect(point).toBeDisabled();
    fireEvent.click(point);
    expect(mocks.sendLiveCommand).toHaveBeenCalledTimes(1);

    settle({ accepted_version: 8, projection: { score: [2, 1], status: 'active', coverage: 'complete' } });
    await waitFor(() => expect(screen.queryByLabelText('Unsaved referee intent')).not.toBeInTheDocument());
  });

  it('restores an unacknowledged command after reload and clears it after acknowledgement', async () => {
    mocks.getLiveGame.mockResolvedValue(baseGame);
    mocks.sendLiveCommand.mockRejectedValueOnce(new Error('connection lost'));
    const firstView = renderGame();
    fireEvent.click(await screen.findByRole('button', { name: 'Point' }));
    expect(await screen.findByText(/Retrying will not create a duplicate/i)).toBeInTheDocument();
    const original = mocks.sendLiveCommand.mock.calls[0][2];
    firstView.unmount();

    mocks.getLiveGame
      .mockReset()
      .mockResolvedValueOnce(baseGame)
      .mockResolvedValue({ ...baseGame, score: [2, 1], version: 8 });
    mocks.sendLiveCommand.mockResolvedValueOnce({ accepted_version: 8, projection: { score: [2, 1], status: 'active', coverage: 'complete' } });
    renderGame();
    expect(await screen.findByText(/could not confirm whether this result saved/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Try saving again' }));
    await waitFor(() => expect(mocks.sendLiveCommand).toHaveBeenCalledTimes(2));
    expect(mocks.sendLiveCommand.mock.calls[1][2]).toEqual(original);
    await waitFor(() => expect(window.localStorage.length).toBe(0));
  });

  it('retains a command ID conflict for review instead of blindly retrying', async () => {
    mocks.getLiveGame.mockResolvedValue(baseGame);
    mocks.sendLiveCommand.mockRejectedValue({
      status: 409,
      detail: { code: 'dice_live.command_id_conflict' },
      message: 'conflict',
    });
    renderGame();
    fireEvent.click(await screen.findByRole('button', { name: 'Point' }));

    expect(await screen.findByText(/save ID conflicts with another result/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Try saving again' })).not.toBeInTheDocument();
    expect(mocks.sendLiveCommand).toHaveBeenCalledTimes(1);
  });

  it('clears a retained command when the signed-in user logs out', async () => {
    mocks.getLiveGame.mockResolvedValue(baseGame);
    mocks.sendLiveCommand.mockRejectedValue(new Error('connection lost'));
    const enabledAuth = { token: 'token', user: { id: 'me' }, features: { dice_live_referee: { opted_in: true, effective: true } } };
    const view = render(
      <MemoryRouter initialEntries={['/dice/live/match-1']}>
        <Routes><Route path="/dice/live/:matchId" element={<LiveGame auth={enabledAuth} />} /></Routes>
      </MemoryRouter>,
    );
    fireEvent.click(await screen.findByRole('button', { name: 'Point' }));
    await screen.findByText(/Retrying will not create a duplicate/i);
    expect(window.localStorage.length).toBe(1);

    const loggedOutAuth = { token: '', user: null, features: enabledAuth.features };
    view.rerender(
      <MemoryRouter initialEntries={['/dice/live/match-1']}>
        <Routes><Route path="/dice/live/:matchId" element={<LiveGame auth={loggedOutAuth} />} /></Routes>
      </MemoryRouter>,
    );
    await waitFor(() => expect(window.localStorage.length).toBe(0));
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

  it('locks an open reopen confirmation while its command is saving', async () => {
    let accept;
    const completion = { id: 'finish-1', kind: 'completion', recorded_by: 'me', sequence: 6 };
    mocks.getLiveGame.mockResolvedValue({ ...baseGame, status: 'completed', version: 8, events: [completion] });
    mocks.sendLiveCommand.mockImplementation(() => new Promise((resolve) => { accept = resolve; }));
    renderGame();

    fireEvent.click(await screen.findByRole('button', { name: 'Reopen game' }));
    const confirm = screen.getByRole('button', { name: 'Confirm reopen' });
    fireEvent.click(confirm);
    expect(confirm).toBeDisabled();

    accept({ accepted_version: 9, projection: { score: [1, 1], status: 'active', coverage: 'complete' } });
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Confirm reopen game' })).not.toBeInTheDocument());
  });

  it('does not allow reopening an optimistically completed game before official history refreshes', async () => {
    mocks.getLiveGame
      .mockResolvedValueOnce(baseGame)
      .mockRejectedValueOnce(new Error('connection lost'));
    mocks.sendLiveCommand.mockResolvedValue({
      accepted_version: 8,
      projection: { score: [5, 3], status: 'completed', coverage: 'complete' },
    });
    renderGame();

    fireEvent.click(await screen.findByRole('button', { name: 'Point' }));

    expect(await screen.findByRole('region', { name: 'Refreshing saved result' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reopen game' })).toBeDisabled();
    expect(screen.getByRole('radio', { name: 'Ranked — Affects ELO' })).toBeDisabled();
  });

  it('resets the visible timer baseline when a completed game is reopened', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-09-04T12:10:00.000Z'));
    const completedAt = '2026-09-04T12:01:00.000Z';
    const reopenedAt = '2026-09-04T12:09:55.000Z';
    mocks.getLiveGame.mockResolvedValue({
      ...baseGame,
      created_at: '2026-09-04T12:00:00.000Z',
      status: 'active',
      events: [
        { id: 'finish-1', kind: 'completion', recorded_at: completedAt },
        { id: 'reopen-1', kind: 'correction', target_event_id: 'finish-1', recorded_at: reopenedAt },
        { id: 'reopen-checkpoint-1', kind: 'score_checkpoint', replacement_for: 'finish-1' },
      ],
    });

    const { container } = renderGame();
    await act(async () => {});

    expect(container.querySelector('.jk-live-status')).toHaveTextContent('In progress · 0:05');
  });

  it('times only the latest active cycle after repeated completion and reopen', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-09-04T12:10:00.000Z'));
    mocks.getLiveGame.mockResolvedValue({
      ...baseGame,
      created_at: '2026-09-04T12:00:00.000Z',
      status: 'active',
      events: [
        { id: 'finish-1', kind: 'completion', recorded_at: '2026-09-04T12:01:00.000Z', sequence: 1 },
        { id: 'reopen-1', kind: 'correction', target_event_id: 'finish-1', recorded_at: '2026-09-04T12:05:00.000Z', sequence: 2 },
        { id: 'finish-2', kind: 'completion', recorded_at: '2026-09-04T12:06:00.000Z', sequence: 3 },
        { id: 'reopen-2', kind: 'correction', target_event_id: 'finish-2', recorded_at: '2026-09-04T12:09:55.000Z', sequence: 4 },
      ],
    });

    const { container } = renderGame();
    await act(async () => {});

    expect(container.querySelector('.jk-live-status')).toHaveTextContent('In progress · 0:05');
  });

  it('does not reset the timer for an atomic replacement final', async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-09-04T12:10:00.000Z'));
    mocks.getLiveGame.mockResolvedValue({
      ...baseGame,
      created_at: '2026-09-04T12:00:00.000Z',
      status: 'completed',
      events: [
        { id: 'finish-1', kind: 'completion', recorded_at: '2026-09-04T12:01:00.000Z', sequence: 1 },
        { id: 'correct-1', kind: 'correction', target_event_id: 'finish-1', recorded_at: '2026-09-04T12:01:05.000Z', sequence: 2 },
        { id: 'finish-2', kind: 'completion', replacement_for: 'finish-1', recorded_at: '2026-09-04T12:01:05.000Z', sequence: 3 },
      ],
    });

    const { container } = renderGame();
    await act(async () => {});

    expect(container.querySelector('.jk-live-status')).toHaveTextContent('Final · 1:05');
  });

  it('guides score catch-up when a correction crosses an absolute checkpoint', async () => {
    const earlierPoint = { id: 'point-1', kind: 'observation', outcome: 'point', thrower_id: 'alice', sequence: 1 };
    const firstCorrection = { id: 'correction-1', kind: 'correction', target_event_id: 'point-1', sequence: 2 };
    const firstReplacement = { id: 'replacement-1', kind: 'observation', outcome: 'miss', thrower_id: 'alice', replacement_for: 'point-1', sequence: 3 };
    const earlierMiss = { id: 'miss-1', kind: 'observation', outcome: 'miss', thrower_id: 'bea', sequence: 4 };
    const completion = { id: 'finish-1', kind: 'completion', sequence: 5 };
    const reopen = { id: 'reopen-1', kind: 'correction', target_event_id: 'finish-1', sequence: 6 };
    const checkpoint = { id: 'checkpoint-1', kind: 'score_checkpoint', score: [5, 3], replacement_for: 'finish-1', sequence: 7 };
    const secondCorrection = { id: 'correction-2', kind: 'correction', target_event_id: 'replacement-1', sequence: 8 };
    const activeReplacement = { id: 'replacement-2', kind: 'observation', outcome: 'point', thrower_id: 'alice', replacement_for: 'replacement-1', sequence: 9 };
    mocks.getLiveGame.mockResolvedValue({
      ...baseGame,
      score: [5, 3],
      events: [earlierPoint, firstCorrection, firstReplacement, earlierMiss, completion, reopen, checkpoint, secondCorrection, activeReplacement],
    });
    renderGame();

    const catchup = await screen.findByRole('region', { name: 'Score checkpoint notice' });
    expect(within(catchup).getByText(/official 5–3 checkpoint keeps the score fixed/i)).toBeInTheDocument();
    fireEvent.click(within(catchup).getByRole('button', { name: 'Catch up score' }));
    expect(screen.getByRole('dialog')).toHaveTextContent('Catch up score');
    expect(screen.getByLabelText('Team 1 score')).toHaveValue(5);
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));

    fireEvent.click(screen.getAllByRole('button', { name: 'Fix this result' })[0]);
    expect(screen.getByText(/before the official 5–3 score checkpoint/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Change recorded result' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Remove mistaken entry' }));
    expect(screen.getByText(/Recorded stats will update, but the official 5–3 checkpoint keeps the score fixed/i)).toBeInTheDocument();
    expect(screen.queryByText('The score will update. History stays intact.')).not.toBeInTheDocument();
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
    fireEvent.click(await screen.findByRole('button', { name: 'Discard unsaved intent' }));
    expect(screen.queryByLabelText('Unsaved referee intent')).not.toBeInTheDocument();
    expect(mocks.sendLiveCommand).toHaveBeenCalledTimes(1);
  });

  it('keeps retry recovery when a stale-version refresh is itself stale', async () => {
    mocks.getLiveGame.mockResolvedValue(baseGame);
    mocks.sendLiveCommand.mockRejectedValue({
      status: 409, detail: { code: 'dice_live.stale_version', current_version: 8 }, message: 'stale',
    });
    renderGame();
    fireEvent.click(await screen.findByRole('button', { name: 'Point' }));
    expect(await screen.findByText(/latest state could not load/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Try saving again' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Save my result now' })).not.toBeInTheDocument();
    expect(screen.getByText('1–1')).toBeInTheDocument();
  });

  it('does not restore classic Dice when a stale flag changes after loading', async () => {
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
    expect(screen.getByText('1–1')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reload' })).toBeInTheDocument();
    expect(mocks.getLiveGame).toHaveBeenCalledTimes(1);
  });
});
