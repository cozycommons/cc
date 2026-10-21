// @vitest-environment-options {"url":"https://commons.example/crowdset"}
import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import Crowdset from './Crowdset';
import { request } from './api';
import { getClient } from '../supabase';

vi.mock('./api', () => ({ request: vi.fn(), getLimits: async () => ({ recordings: 64 }), endpoint: (path) => `/crowdset/sets${path}` }));
vi.mock('../supabase', () => ({ getClient: vi.fn() }));
const session = { user: { id: 'first' } };
const set = { id: 'set', slug: 'test-set', name: 'Test set', status: 'ready', playable: true, video_playable: true,
  mix_revision: 'same-cut', clips: [], timeline: { duration: 100, segments: [] }, video_timeline: { duration: 100, segments: [] } };
let authChanged;
function mount() {
  return render(<BrowserRouter><Routes><Route path="/crowdset/:slug?" element={<Crowdset />} /></Routes></BrowserRouter>);
}
async function openPlayer() {
  mount();
  const player = await screen.findByLabelText('Current cut');
  player.currentTime = 42;
  Object.defineProperty(player, 'paused', { configurable: true, value: false });
  fireEvent.play(player);
  return player;
}
beforeEach(() => {
  localStorage.clear();
  window.history.replaceState({}, '', '/crowdset/test-set');
  request.mockReset().mockResolvedValue([set]);
  getClient.mockImplementation(() => ({ auth: { onAuthStateChange: (callback) => {
    authChanged = callback;
    callback('INITIAL_SESSION', session);
    return { data: { subscription: { unsubscribe: vi.fn() } } };
  } } }));
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true }));
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {});
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it.each(['SIGNED_IN', 'TOKEN_REFRESHED'])('keeps the playing video mounted during %s for the same user', async (event) => {
  const player = await openPlayer();
  let finish;
  request.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  act(() => authChanged(event, session));
  await waitFor(() => expect(finish).toBeTypeOf('function'));
  expect(screen.getByLabelText('Current cut')).toBe(player);
  expect(player.currentTime).toBe(42);
  expect(player.paused).toBe(false);
  await act(async () => finish([{ ...set }]));
  expect(screen.getByLabelText('Current cut')).toBe(player);
  expect(player.currentTime).toBe(42);
  expect(player.paused).toBe(false);
});

it('keeps playback on a transient background refresh error', async () => {
  const player = await openPlayer();
  request.mockRejectedValueOnce(Object.assign(new Error('Temporary verification failure'), { status: 503 }));
  act(() => authChanged('TOKEN_REFRESHED', session));
  await screen.findByRole('alert');
  expect(screen.getByLabelText('Current cut')).toBe(player);
  expect(player.currentTime).toBe(42);
  expect(player.paused).toBe(false);
});

it('does not restore private data from a refresh that finishes after sign-out', async () => {
  await openPlayer();
  let finish;
  request.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  act(() => authChanged('SIGNED_IN', session));
  await waitFor(() => expect(finish).toBeTypeOf('function'));
  act(() => authChanged('SIGNED_OUT', null));
  await screen.findByRole('heading', { name: 'Sign in' });
  await act(async () => finish([set]));
  expect(screen.queryByLabelText('Current cut')).not.toBeInTheDocument();
  expect(screen.getByRole('heading', { name: 'Sign in' })).toBeInTheDocument();
});

it('removes the old player when the signed-in account changes', async () => {
  await openPlayer();
  let finish;
  request.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  act(() => authChanged('SIGNED_IN', { user: { id: 'second' } }));
  await waitFor(() => expect(finish).toBeTypeOf('function'));
  expect(screen.queryByLabelText('Current cut')).not.toBeInTheDocument();
  await act(async () => finish([]));
  expect(screen.getByRole('heading', { name: 'Set unavailable' })).toBeInTheDocument();
});

it('removes playback when the server rejects a refreshed session', async () => {
  await openPlayer();
  request.mockRejectedValueOnce(Object.assign(new Error('Sign in'), { status: 401 }));
  act(() => authChanged('TOKEN_REFRESHED', session));
  await screen.findByRole('heading', { name: 'Sign in' });
  expect(screen.queryByLabelText('Current cut')).not.toBeInTheDocument();
});

it('remembers theater mode across page remounts', async () => {
  let view = mount();
  await screen.findByLabelText('Current cut');
  fireEvent.click(screen.getByRole('button', { name: 'Theater mode', exact: true }));
  expect(screen.getByRole('main')).toHaveClass('cs-theater');
  view.unmount();
  view = mount();
  await screen.findByLabelText('Current cut');
  expect(screen.getByRole('main')).toHaveClass('cs-theater');
  view.unmount();
});
