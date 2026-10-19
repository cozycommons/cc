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

it('uses screen and icon buttons, restores mute volume, and seeks with focused shortcuts', async () => {
  render(<CompositionPlayer set={{ ...set, video_timeline: { ...set.video_timeline, duration: 120 } }} playerRef={playerRef} onTimeUpdate={() => {}} />);
  const base = playerRef.current;
  fireEvent.click(screen.getByRole('button', { name: 'Play video' }));
  await act(async () => {});
  expect(base.paused).toBe(false);
  fireEvent.play(base);
  fireEvent.click(screen.getByRole('button', { name: 'Pause video' }));
  expect(base.paused).toBe(true);
  fireEvent.change(screen.getByRole('slider', { name: 'Volume' }), { target: { value: '0.35' } });
  expect(base.volume).toBe(0.35);
  fireEvent.click(screen.getByRole('button', { name: 'Mute', exact: true }));
  expect(base.muted).toBe(true);
  fireEvent.click(screen.getByRole('button', { name: 'Unmute', exact: true }));
  expect(base.muted).toBe(false);
  expect(base.volume).toBe(0.35);
  fireEvent.change(screen.getByRole('slider', { name: 'Seek video' }), { target: { value: '42' } });
  fireEvent.keyDown(screen.getByRole('region', { name: 'Video player' }), { key: 'l' });
  expect(base.currentTime).toBe(52);
  fireEvent.keyDown(screen.getByRole('slider', { name: 'Seek video' }), { key: 'ArrowRight' });
  expect(base.currentTime).toBe(52); // Native range handles its own arrows.
});

it('supports theater and a fullscreen fallback that includes both video layers', async () => {
  const theater = vi.fn();
  const view = render(<CompositionPlayer set={set} playerRef={playerRef} onTimeUpdate={() => {}} onTheaterChange={theater} />);
  fireEvent.click(screen.getByRole('button', { name: 'Theater mode', exact: true }));
  expect(theater).toHaveBeenCalledWith(true);
  fireEvent.click(screen.getByRole('button', { name: 'Fullscreen', exact: true }));
  await act(async () => {});
  const player = screen.getByRole('region', { name: 'Video player' });
  expect(player).toHaveClass('cs-player-expanded');
  expect(player.contains(screen.getByLabelText('Friend’s picture'))).toBe(true);
  expect(document.body.style.overflow).toBe('hidden');
  fireEvent.keyDown(document, { key: 'Escape' });
  expect(player).not.toHaveClass('cs-player-expanded');
  expect(document.body.style.overflow).not.toBe('hidden');
  fireEvent.click(screen.getByRole('button', { name: 'Fullscreen', exact: true }));
  view.unmount();
  expect(document.body.style.overflow).not.toBe('hidden');
});

it('auto-hides controls only while playing and shows them on interaction or buffering', async () => {
  vi.useFakeTimers();
  render(<CompositionPlayer set={set} playerRef={playerRef} onTimeUpdate={() => {}} />);
  const player = screen.getByRole('region', { name: 'Video player' });
  fireEvent.play(playerRef.current);
  act(() => vi.advanceTimersByTime(3100));
  expect(player).not.toHaveClass('cs-controls-visible');
  fireEvent.pointerMove(player);
  expect(player).toHaveClass('cs-controls-visible');
  act(() => vi.advanceTimersByTime(3100));
  fireEvent.waiting(playerRef.current);
  expect(screen.getByRole('status', { name: 'Buffering video' })).toBeInTheDocument();
  expect(player).toHaveClass('cs-controls-visible');
  fireEvent.pause(playerRef.current);
  expect(screen.queryByRole('status', { name: 'Buffering video' })).not.toBeInTheDocument();
  vi.useRealTimers();
});


it('tracks browser fullscreen changes rather than guessing its state', async () => {
  render(<CompositionPlayer set={set} playerRef={playerRef} onTimeUpdate={() => {}} />);
  const player = screen.getByRole('region', { name: 'Video player' });
  player.requestFullscreen = vi.fn(async () => {
    Object.defineProperty(document, 'fullscreenElement', { configurable: true, value: player });
    document.dispatchEvent(new Event('fullscreenchange'));
  });
  fireEvent.click(screen.getByRole('button', { name: 'Fullscreen', exact: true }));
  await screen.findByRole('button', { name: 'Exit fullscreen' });
  expect(player.requestFullscreen).toHaveBeenCalledOnce();
  act(() => {
    Object.defineProperty(document, 'fullscreenElement', { configurable: true, value: null });
    document.dispatchEvent(new Event('fullscreenchange'));
  });
  expect(screen.getByRole('button', { name: 'Fullscreen', exact: true })).toBeInTheDocument();
});
