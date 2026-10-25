import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, expect, it, vi } from 'vitest';
import Fantasy from './Fantasy.jsx';
import { cachedSnapshot, cleanSnapshot, loadSnapshot } from './source.js';
import { SNAPSHOT_V2 } from './fixture.js';
vi.mock('../api.js', () => ({ getUrl: () => null }));
vi.mock('./source.js', async original => ({ ...await original(), loadSnapshot: vi.fn(), cachedSnapshot: vi.fn() }));
afterEach(() => { vi.clearAllMocks(); localStorage.clear(); });
const mount = () => render(<MemoryRouter><Fantasy /></MemoryRouter>);
const data = cleanSnapshot(SNAPSHOT_V2);
const slots = data.matchups.map(({ key, home, away }) => ({ key, home, away }));
const meta = { ...data, matchups: undefined, totalMatchups: slots.length, slots };

it('fills stable slots cumulatively and resets safely on a new stream', async () => {
  let emit, resolve;
  loadSnapshot.mockImplementation((_url, _signal, callback) => { emit = callback; return new Promise(done => { resolve = done; }); });
  mount();
  act(() => emit({ meta, matchups: [], done: false, error: null }));
  expect(screen.getByText(`0 of ${slots.length}`)).toBeTruthy();
  const match = data.matchups.find(m => !m.unavailable);
  act(() => emit({ meta, matchups: [match], done: false, error: null }));
  const card = screen.getByRole('link', { name: new RegExp(`${match.home.name} vs`) });
  expect(document.querySelectorAll('.fx-skeleton')).toHaveLength(slots.length - 1);
  act(() => emit({ meta, matchups: data.matchups, done: false, error: null }));
  expect(screen.getByRole('link', { name: new RegExp(`${match.home.name} vs`) })).toBe(card);
  act(() => emit({ meta, matchups: [], done: false, error: null }));
  expect(document.querySelectorAll('.fx-skeleton')).toHaveLength(slots.length);
  await act(async () => { emit({ meta, matchups: data.matchups, done: true, error: null }); resolve(data); });
  expect(document.querySelector('.fx-loading')).toBeNull();
  expect(document.querySelectorAll('.fx-skeleton')).toHaveLength(0);
});

it('retries after failure with a fresh signal and preserves saved data', async () => {
  loadSnapshot.mockRejectedValueOnce(new Error('stalled')).mockResolvedValueOnce(data);
  const first = mount();
  fireEvent.click(await screen.findByRole('button', { name: 'Try again' }));
  await screen.findByRole('link', { name: /Harbor Hoopers vs/ });
  const [before, after] = loadSnapshot.mock.calls.map(call => call[1]);
  expect(before.aborted).toBe(true);
  expect(after).not.toBe(before);
  first.unmount();
  cachedSnapshot.mockReturnValue(data);
  loadSnapshot.mockRejectedValue(new Error('offline'));
  mount();
  await waitFor(() => expect(document.querySelectorAll('.fx-card--link').length).toBeGreaterThan(0));
  expect(screen.queryByText('Shot clock ran out.')).toBeNull();
});
