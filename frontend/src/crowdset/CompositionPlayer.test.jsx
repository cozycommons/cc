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
  localStorage.clear();
  vi.stubGlobal('requestAnimationFrame', (cb) => { callback = cb; return 1; });
  vi.stubGlobal('cancelAnimationFrame', vi.fn());
  vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(function () { this.currentTime = 0; });
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(function () { Object.defineProperty(this, 'paused', { configurable: true, value: true }); });
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(function () { Object.defineProperty(this, 'paused', { configurable: true, value: false }); return Promise.resolve(); });
  playerRef = React.createRef();
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it('remembers volume and mute across player remounts without starting playback', async () => {
  let view = render(<CompositionPlayer set={set} playerRef={playerRef} onTimeUpdate={() => {}} />);
  fireEvent.change(screen.getByRole('slider', { name: 'Volume' }), { target: { value: '0.35' } });
  fireEvent.volumeChange(playerRef.current);
  fireEvent.click(screen.getByRole('button', { name: 'Mute', exact: true }));
  fireEvent.volumeChange(playerRef.current);
  view.unmount();
  view = render(<CompositionPlayer set={set} playerRef={playerRef} onTimeUpdate={() => {}} />);
  expect(playerRef.current.volume).toBe(0.35);
  expect(playerRef.current.muted).toBe(true);
  expect(screen.getByRole('button', { name: 'Unmute', exact: true })).toBeInTheDocument();
  expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Unmute', exact: true }));
  expect(playerRef.current.volume).toBe(0.35);
  view.unmount();
});

it('uses safe defaults for corrupt preferences and works when storage is unavailable', () => {
  localStorage.setItem('crowdset:player', '{broken');
  const view = render(<CompositionPlayer set={set} playerRef={playerRef} onTimeUpdate={() => {}} />);
  expect(playerRef.current.volume).toBe(1);
  view.unmount();
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('Storage disabled'); });
  vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('Storage disabled'); });
  render(<CompositionPlayer set={set} playerRef={playerRef} onTimeUpdate={() => {}} />);
  fireEvent.change(screen.getByRole('slider', { name: 'Volume' }), { target: { value: '0.4' } });
  fireEvent.volumeChange(playerRef.current);
  expect(playerRef.current.volume).toBe(0.4);
});

it('switches only muted picture, preloads, seeks, pauses and falls back on errors', async () => {
  render(<CompositionPlayer set={set} playerRef={playerRef} onTimeUpdate={() => {}} />);
  const base = screen.getByLabelText('Current cut');
  const insert = screen.getByLabelText('Friend’s picture');
  for (const media of [base, insert]) Object.defineProperty(media, 'readyState', { configurable: true, value: 4 });
  tick(6);
  expect(insert).toHaveAttribute('src', '/crowdset/sets/set/overlays/friend?v=revision');
  expect(insert.style.visibility).toBe('hidden');
  fireEvent.click(screen.getByRole('button', { name: 'Play' }));
  await act(async () => {});
  tick(12); fireEvent.seeked(insert); tick(12);
  expect(insert.currentTime).toBe(2);
  expect(insert.style.visibility).toBe('visible');
  expect(insert.muted).toBe(true);
  expect(base.muted).toBe(false);
  expect(base).toHaveAttribute('src', '/crowdset/sets/set/video?v=revision');
  Object.defineProperty(base, 'paused', { configurable: true, value: true });
  tick(13); fireEvent.seeked(insert); tick(13);
  expect(insert.paused).toBe(true);
  Object.defineProperty(insert, 'readyState', { configurable: true, value: 1 });
  tick(14);
  expect(insert.style.visibility).toBe('visible');
  Object.defineProperty(insert, 'readyState', { configurable: true, value: 4 });
  tick(15); tick(15);
  fireEvent.error(insert);
  tick(16);
  expect(insert.style.visibility).toBe('hidden');
  tick(21);
  expect(insert).toHaveAttribute('src', '/crowdset/sets/set/overlays/next?v=revision');
  tick(26); fireEvent.seeked(insert); tick(26);
  expect(insert.style.visibility).toBe('visible');
  tick(5);
  expect(insert.style.visibility).toBe('hidden');
  expect(base).toHaveAttribute('src', '/crowdset/sets/set/video?v=revision');
});

it('waits for a presented frame and tolerates small drift without seeking or flashing the base', async () => {
  render(<CompositionPlayer set={set} playerRef={playerRef} onTimeUpdate={() => {}} />);
  const insert = screen.getByLabelText('Friend’s picture');
  let presented;
  insert.requestVideoFrameCallback = vi.fn((cb) => { presented = cb; return 1; });
  insert.cancelVideoFrameCallback = vi.fn();
  for (const media of [playerRef.current, insert]) Object.defineProperty(media, 'readyState', { configurable: true, value: 4 });
  tick(12);
  expect(insert.style.visibility).toBe('hidden');
  fireEvent.seeked(insert);
  expect(insert.style.visibility).toBe('hidden');
  act(() => presented(0, { mediaTime: 0 }));
  expect(insert.style.visibility).toBe('hidden');
  tick(12);
  act(() => presented(0, { mediaTime: 2 }));
  expect(insert.style.visibility).toBe('visible');
  fireEvent.click(screen.getByRole('button', { name: 'Play' }));
  await act(async () => {});
  tick(12.25);
  expect(insert.currentTime).toBe(2);
  expect(insert.playbackRate).toBeGreaterThan(1);
  expect(insert.style.visibility).toBe('visible');
  Object.defineProperty(insert, 'readyState', { configurable: true, value: 1 });
  tick(12.3);
  expect(insert.style.visibility).toBe('visible');
  tick(20);
  expect(insert.style.visibility).toBe('hidden');
});

it('reveals a preloaded clip at its start in browsers without compositor callbacks', () => {
  render(<CompositionPlayer set={set} playerRef={playerRef} onTimeUpdate={() => {}} />);
  const insert = screen.getByLabelText('Friend’s picture');
  for (const media of [playerRef.current, insert]) Object.defineProperty(media, 'readyState', { configurable: true, value: 4 });
  tick(6);
  fireEvent.loadedData(insert);
  expect(insert.style.visibility).toBe('hidden');
  tick(10);
  expect(insert.style.visibility).toBe('visible');
});

it('reuses the decoded first frame when seeking exactly to a preloaded clip’s start', () => {
  render(<CompositionPlayer set={set} playerRef={playerRef} onTimeUpdate={() => {}} />);
  const insert = screen.getByLabelText('Friend’s picture');
  let presented;
  insert.requestVideoFrameCallback = vi.fn((cb) => { presented = cb; return 1; });
  insert.cancelVideoFrameCallback = vi.fn();
  for (const media of [playerRef.current, insert]) Object.defineProperty(media, 'readyState', { configurable: true, value: 4 });
  tick(6);
  fireEvent.loadedData(insert);
  act(() => presented(0, { mediaTime: 0 }));
  tick(10);
  expect(insert.style.visibility).toBe('visible');
  expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled();
});

it('holds the last picture during a paused seek and reveals the new frame without starting audio', () => {
  const draw = vi.fn();
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue({ drawImage: draw });
  let now = 0;
  vi.spyOn(performance, 'now').mockImplementation(() => now);
  render(<CompositionPlayer set={set} playerRef={playerRef} onTimeUpdate={() => {}} />);
  const insert = screen.getByLabelText('Friend’s picture');
  const still = document.querySelector('.cs-composition-still');
  for (const media of [playerRef.current, insert]) Object.defineProperty(media, 'readyState', { configurable: true, value: 4 });
  Object.defineProperties(insert, { videoWidth: { value: 1920 }, videoHeight: { value: 1080 } });
  tick(12); fireEvent.seeked(insert); tick(12);
  now = 1200;
  tick(16);
  expect(draw).toHaveBeenCalledOnce();
  expect(still.width).toBe(1280);
  expect(still.style.visibility).toBe('visible');
  expect(insert.style.visibility).toBe('hidden');
  tick(16.1);
  expect(insert.currentTime).toBe(6);
  expect(still.style.visibility).toBe('visible');
  fireEvent.seeked(insert);
  expect(insert.style.visibility).toBe('visible');
  expect(still.style.visibility).toBe('hidden');
  expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled();
  expect(playerRef.current.muted).toBe(false);
});

it('ignores stale decoded callbacks after a different clip is selected and cancels on unmount', () => {
  const view = render(<CompositionPlayer set={set} playerRef={playerRef} onTimeUpdate={() => {}} />);
  const insert = screen.getByLabelText('Friend’s picture');
  let presented;
  insert.requestVideoFrameCallback = vi.fn((cb) => { presented = cb; return 1; });
  insert.cancelVideoFrameCallback = vi.fn();
  for (const media of [playerRef.current, insert]) Object.defineProperty(media, 'readyState', { configurable: true, value: 4 });
  tick(12);
  const stale = presented;
  tick(26);
  fireEvent.seeked(insert);
  act(() => stale(0, { mediaTime: 1 }));
  expect(insert.style.visibility).toBe('hidden');
  act(() => presented(0, { mediaTime: 1 }));
  expect(insert.style.visibility).toBe('visible');
  tick(26);
  view.unmount();
  expect(insert.cancelVideoFrameCallback).toHaveBeenCalled();
  act(() => presented(0, { mediaTime: 1 }));
  expect(insert.style.visibility).toBe('hidden');
});

it('falls back to the official picture if a corrective seek never completes', () => {
  let now = 0;
  vi.spyOn(performance, 'now').mockImplementation(() => now);
  render(<CompositionPlayer set={set} playerRef={playerRef} onTimeUpdate={() => {}} />);
  const insert = screen.getByLabelText('Friend’s picture');
  for (const media of [playerRef.current, insert]) Object.defineProperty(media, 'readyState', { configurable: true, value: 4 });
  tick(12);
  now = 6000;
  tick(13);
  expect(insert.style.visibility).toBe('hidden');
  fireEvent.seeked(insert);
  expect(insert.style.visibility).toBe('hidden');
  expect(playerRef.current).toHaveAttribute('src', '/crowdset/sets/set/video?v=revision');
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

it('handles page shortcuts but leaves typing, modifiers, original clips, and native controls alone', async () => {
  const theater = vi.fn();
  render(<><input aria-label="Comment" /><textarea aria-label="Notes" /><div contentEditable suppressContentEditableWarning aria-label="Editor">Text</div><article><video aria-label="Original" /></article><CompositionPlayer set={{ ...set, video_timeline: { ...set.video_timeline, duration: 100 } }} playerRef={playerRef} onTimeUpdate={() => {}} onTheaterChange={theater} /></>);
  fireEvent.keyDown(document.body, { key: '5' });
  expect(playerRef.current.currentTime).toBe(50);
  fireEvent.keyDown(document.body, { key: 'j' });
  expect(playerRef.current.currentTime).toBe(40);
  fireEvent.keyDown(document.body, { key: 'ArrowRight' });
  expect(playerRef.current.currentTime).toBe(45);
  fireEvent.keyDown(document.body, { key: 'm' });
  expect(playerRef.current.muted).toBe(true);
  fireEvent.keyDown(document.body, { key: 't' });
  expect(theater).toHaveBeenCalledWith(true);
  for (const label of ['Comment', 'Notes', 'Editor', 'Original', 'Seek video', 'Volume']) fireEvent.keyDown(screen.getByLabelText(label), { key: '0' });
  fireEvent.keyDown(document.body, { key: '0', ctrlKey: true });
  fireEvent.keyDown(document.body, { key: '0', isComposing: true });
  expect(playerRef.current.currentTime).toBe(45);
  fireEvent.keyDown(document.body, { key: 'k', repeat: true });
  expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled();
  fireEvent.keyDown(document.body, { key: 'k' });
  await act(async () => {});
  expect(playerRef.current.paused).toBe(false);
  fireEvent.keyDown(document.body, { key: ' ' });
  expect(playerRef.current.paused).toBe(true);
  fireEvent.keyDown(document.body, { key: 'Home' });
  expect(playerRef.current.currentTime).toBe(0);
  fireEvent.keyDown(document.body, { key: 'End' });
  expect(playerRef.current.currentTime).toBe(100);
});

it('previews the seek position without moving the main video and labels control shortcuts', () => {
  vi.useFakeTimers();
  vi.stubGlobal('PointerEvent', MouseEvent);
  const view = render(<CompositionPlayer set={{ ...set, video_timeline: { ...set.video_timeline, duration: 100 } }} playerRef={playerRef} onTimeUpdate={() => {}} onTheaterChange={() => {}} />);
  const slider = screen.getByRole('slider', { name: 'Seek video' });
  slider.getBoundingClientRect = () => ({ left: 0, width: 100 });
  playerRef.current.currentTime = 3;
  fireEvent.pointerMove(slider, { clientX: 14 });
  expect(screen.getByRole('img', { name: 'Video preview at 0:14' })).toBeInTheDocument();
  expect(playerRef.current.currentTime).toBe(3);
  expect(view.container.querySelector('.cs-scrub-picture video')).toBeNull();
  expect(screen.queryByText('Loading preview…')).toBeNull();
  fireEvent.pointerLeave(slider);
  expect(screen.queryByRole('img', { name: /Video preview/ })).not.toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Play', exact: true })).toHaveAttribute('aria-keyshortcuts', 'Space K');
  expect(screen.getByText('Theater mode (T)')).toBeInTheDocument();
  expect(screen.getByText('Fullscreen (F)')).toBeInTheDocument();
  fireEvent.play(playerRef.current);
  expect(screen.getByText('Pause (K)')).toBeInTheDocument();
  vi.useRealTimers();
});


it('keeps letter shortcuts available after using the seek bar without replacing native range keys', async () => {
  render(<CompositionPlayer set={{ ...set, video_timeline: { ...set.video_timeline, duration: 100 } }} playerRef={playerRef} onTimeUpdate={() => {}} />);
  const seek = screen.getByRole('slider', { name: 'Seek video' });
  fireEvent.keyDown(seek, { key: 'k' });
  await act(async () => {});
  expect(playerRef.current.paused).toBe(false);
  fireEvent.keyDown(seek, { key: 'm' });
  expect(playerRef.current.muted).toBe(true);
  fireEvent.keyDown(seek, { key: 'l' });
  expect(playerRef.current.currentTime).toBe(10);
  fireEvent.keyDown(seek, { key: 'ArrowRight' });
  expect(playerRef.current.currentTime).toBe(10);
});
