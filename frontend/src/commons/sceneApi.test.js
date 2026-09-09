import { afterEach, describe, expect, it, vi } from 'vitest';
import { getScene } from './sceneApi.js';

describe('Commons scene API timing', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('attaches a non-enumerable midpoint and RTT uncertainty sample', async () => {
    const scene = { server_time_ms: 1800000000000, state: {} };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue(scene),
    });
    vi.stubGlobal('fetch', fetchMock);
    vi.stubGlobal('performance', { now: vi.fn()
      .mockReturnValueOnce(100)
      .mockReturnValueOnce(260) });
    vi.spyOn(Date, 'now').mockReturnValue(1800000000100);

    const result = await getScene();

    expect(result).toBe(scene);
    expect(result.__client_timing).toEqual({ midpoint_ms: 1800000000180, uncertainty_ms: 80 });
    expect(Object.keys(result)).not.toContain('__client_timing');
  });
});
