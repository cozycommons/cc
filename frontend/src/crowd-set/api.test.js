import { afterEach, expect, it, vi } from 'vitest';
import { request } from './api';

afterEach(() => vi.unstubAllGlobals());

it('shows actionable server validation errors without discarding the status', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 422, json: async () => ({ detail: [{ msg: 'This local time is ambiguous. Choose an explicit offset.' }] }) }));
  await expect(request('', { method: 'POST' })).rejects.toMatchObject({ status: 422, message: 'This local time is ambiguous. Choose an explicit offset.' });
});
