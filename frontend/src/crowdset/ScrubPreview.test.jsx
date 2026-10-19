import React from 'react';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import ScrubPreview, { previewFrame } from './ScrubPreview';

vi.mock('./api', () => ({ endpoint: (path) => `/crowdset/sets${path}` }));
const set = { id: 'set', mix_revision: 'revision', video_timeline: { segments: [{ start: 10, end: 20, asset_id: 'friend' }] } };
beforeEach(() => {
  vi.useFakeTimers();
  vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => {});
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {});
  vi.spyOn(HTMLMediaElement.prototype, 'play').mockImplementation(() => Promise.resolve());
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.useRealTimers(); });

it('selects the published friend picture at exact boundaries with segment-relative seeking', () => {
  expect(previewFrame(set, 9).localTime).toBe(9);
  expect(previewFrame(set, 10)).toEqual({ src: '/crowdset/sets/set/overlays/friend?v=revision', localTime: 0 });
  expect(previewFrame(set, 14).localTime).toBe(4);
  expect(previewFrame(set, 20)).toEqual({ src: '/crowdset/sets/set/video?v=revision', localTime: 20 });
});

it('debounces scrubbing, hides stale frames, never plays, and releases media on exit', () => {
  const view = render(<ScrubPreview set={set} time={11} left="50%" label="0:11" />);
  expect(view.container.querySelector('video')).toBeNull();
  act(() => vi.advanceTimersByTime(100));
  view.rerender(<ScrubPreview set={set} time={14} left="70%" label="0:14" />);
  act(() => vi.advanceTimersByTime(100));
  expect(view.container.querySelector('video')).toBeNull();
  act(() => vi.advanceTimersByTime(80));
  const video = view.container.querySelector('video');
  Object.defineProperties(video, { readyState: { configurable: true, value: 4 }, duration: { configurable: true, value: 10 } });
  fireEvent.loadedMetadata(video);
  expect(video.currentTime).toBe(4);
  expect(video.muted).toBe(true);
  expect(video.style.visibility).toBe('hidden');
  fireEvent.seeked(video);
  expect(video.style.visibility).toBe('visible');
  view.rerender(<ScrubPreview set={set} time={16} left="80%" label="0:16" />);
  expect(video.style.visibility).toBe('hidden');
  fireEvent.seeked(video);
  expect(video.style.visibility).toBe('hidden');
  act(() => vi.advanceTimersByTime(180));
  expect(video.currentTime).toBe(6);
  fireEvent.seeked(video);
  expect(video.style.visibility).toBe('visible');
  expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled();
  view.unmount();
  expect(video).not.toHaveAttribute('src');
  expect(HTMLMediaElement.prototype.load).toHaveBeenCalled();
});

it('shows a timestamp and an unavailable state if the preview cannot load', () => {
  const view = render(<ScrubPreview set={set} time={5} left="10%" label="0:05" />);
  act(() => vi.advanceTimersByTime(180));
  fireEvent.error(view.container.querySelector('video'));
  expect(screen.getByText('Preview unavailable')).toBeInTheDocument();
  expect(screen.getByText('0:05')).toBeInTheDocument();
});
