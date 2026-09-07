import { afterEach, describe, expect, it, vi } from 'vitest';
import { diceApi } from './api.js';

describe('Dice API', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('does not reuse cached state for refresh-sensitive reads', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue([]),
    });
    vi.stubGlobal('fetch', fetchMock);

    await diceApi.getVirtualPicks('token', 'tournament-1');

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/dice/virtual/tournaments/tournament-1/picks'),
      expect.objectContaining({ method: 'GET', cache: 'no-store' }),
    );
  });

  it('sends the caller idempotency key when creating a game', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({ id: 'game-1' }),
    });
    vi.stubGlobal('fetch', fetchMock);

    await diceApi.createGame('token', { team1_score: 5 }, '7aa0729b-56c5-47b1-acf3-01d8827cc06f');

    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/dice/games'),
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({
          Authorization: 'Bearer token',
          'Idempotency-Key': '7aa0729b-56c5-47b1-acf3-01d8827cc06f',
        }),
      }),
    );
  });
});
