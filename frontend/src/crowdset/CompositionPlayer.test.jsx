import React from 'react';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import CompositionPlayer from './CompositionPlayer';

vi.mock('./api', () => ({ endpoint: (path) => `/crowdset/sets${path}` }));
const set = { id: 'set', mix_revision: 'revision', video_timeline: { segments: [
  { start: 10, end: 20, asset_id: 'friend' }, { start: 25, end: 30, asset_id: 'next' },
] } };
let callback;
let playerRef;
function tick(time) { act(() => { playerRef.current.currentTime = time; callback(); }); }
beforeEach(() => {
  vi.stubGlobal('requestAnimationFrame', (cb) => { callback = cb; return 1; });
  vi.stubGlobal('cancelAnimationFrame', vi.fn());
  vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => {});
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(function () { Object.defineProperty(this, 'paused', { configurable: true, value: true }); });
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(function () { Object.defineProperty(this, 'paused', { configurable: true, value: false }); return Promise.resolve(); });
  playerRef = React.createRef();
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it('switches only muted picture, preloads, seeks, pauses and falls back on buffering or errors', async () => {
  render(<CompositionPlayer set={set} playerRef={playerRef} onTimeUpdate={() => {}} />);
  const base = screen.getByLabelText('Current cut');
  const insert = screen.getByLabelText('Friend’s picture');
  for (const media of [base, insert]) Object.defineProperty(media, 'readyState', { configurable: true, value: 4 });
  tick(6);
  expect(insert).toHaveAttribute('src', '/crowdset/sets/set/overlays/friend?v=revision');
  expect(insert.style.visibility).toBe('hidden');
  fireEvent.click(screen.getByRole('button', { name: 'Play' }));
  await act(async () => {});
  tick(12); tick(12);
  expect(insert.currentTime).toBe(2);
  expect(insert.style.visibility).toBe('visible');
  expect(insert.muted).toBe(true);
  expect(base.muted).toBe(false);
  expect(base).toHaveAttribute('src', '/crowdset/sets/set/video?v=revision');
  Object.defineProperty(base, 'paused', { configurable: true, value: true });
  tick(13); tick(13);
  expect(insert.paused).toBe(true);
  Object.defineProperty(insert, 'readyState', { configurable: true, value: 1 });
  tick(14);
  expect(insert.style.visibility).toBe('hidden');
  Object.defineProperty(insert, 'readyState', { configurable: true, value: 4 });
  tick(15); tick(15);
  fireEvent.error(insert);
  tick(16);
  expect(insert.style.visibility).toBe('hidden');
  tick(21);
  expect(insert).toHaveAttribute('src', '/crowdset/sets/set/overlays/next?v=revision');
  tick(26); tick(26);
  expect(insert.style.visibility).toBe('visible');
  tick(5);
  expect(insert.style.visibility).toBe('hidden');
  expect(base).toHaveAttribute('src', '/crowdset/sets/set/video?v=revision');
});
