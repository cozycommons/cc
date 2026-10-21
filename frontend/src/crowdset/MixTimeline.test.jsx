import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import MixTimeline, { recordingColor } from './MixTimeline';

afterEach(cleanup);
const clips = [{ id: 'a', name: 'Stage.mp4' }, { id: 'b', name: 'Balcony.mp4' }, { id: 'unused', name: 'Unselected.mp4' }];
const timeline = { duration: 100, segments: [
  { clip_id: 'a', start: 0, end: 40, fade_in: 0 },
  { clip_id: 'b', start: 39.92, end: 70, fade_in: 0.08 },
  { clip_id: 'a', start: 80, end: 100, fade_in: 0 },
], gaps: [{ start: 70, end: 80 }] };

it('renders one proportional strip from selected segments with source controls, gaps and fades', () => {
  const { container } = render(<MixTimeline timeline={timeline} clips={clips} currentTime={75} onSeek={() => {}} />);
  expect(container.querySelectorAll('svg')).toHaveLength(1);
  const segments = container.querySelectorAll('rect > title');
  expect(segments).toHaveLength(3);
  expect(segments[0].parentElement).toHaveAttribute('width', '400');
  expect(segments[1].parentElement).toHaveAttribute('x', '399.2');
  expect(segments[1].parentElement).toHaveAttribute('fill', recordingColor('b', clips));
  expect(recordingColor('a', clips)).not.toBe(recordingColor('b', clips));
  expect(screen.getByRole('button', { name: 'Stage.mp4' })).toHaveAttribute('title', 'Jump to 0:00 · Stage.mp4');
  expect(screen.queryByRole('button', { name: 'Unselected.mp4' })).not.toBeInTheDocument();
  expect(screen.getByText('Silence')).toBeInTheDocument();
  expect(screen.queryByText('Striped edge: crossfade')).not.toBeInTheDocument();
  expect(screen.getByRole('slider', { name: 'Seek mix' })).toHaveAttribute('aria-valuetext', '1:15 of 1:40');
});

it('seeks within the full duration and identifies both sources during a crossfade', () => {
  const seek = vi.fn();
  render(<MixTimeline timeline={timeline} clips={clips} currentTime={39.95} onSeek={seek} />);
  expect(screen.getByText('Stage.mp4 + Balcony.mp4 · Crossfade')).toBeInTheDocument();
  fireEvent.change(screen.getByRole('slider'), { target: { value: '82.5' } });
  expect(seek).toHaveBeenCalledWith(82.5);
});

it('jumps labels to the earliest appearance, including repeated and unsorted segments', () => {
  const seek = vi.fn();
  render(<MixTimeline timeline={{ ...timeline, segments: [...timeline.segments].reverse() }} clips={clips} currentTime={90} onSeek={seek} />);
  fireEvent.click(screen.getByRole('button', { name: 'Stage.mp4' }));
  expect(seek).toHaveBeenLastCalledWith(0);
  fireEvent.click(screen.getByRole('button', { name: 'Balcony.mp4' }));
  expect(seek).toHaveBeenLastCalledWith(39.92);
});

it('shows cached timeline previews without seeking and supports keyboard inspection', () => {
  vi.stubGlobal('PointerEvent', MouseEvent);
  const seek = vi.fn();
  const set = { id: 'set', mix_revision: 'revision', video_timeline: { segments: [{ clip_id: 'b', start: 20, end: 70, offset: 20 }] },
    scrub_previews: { b: { interval: 10, start: 0, count: 5, columns: 5, rows: 1, sheets: ['sheet.jpg'] } } };
  const previews = new Map([['http://127.0.0.1:8010/crowdset/sets/set/previews/sheet.jpg?v=revision', 'blob:cached']]);
  const view = render(<MixTimeline timeline={timeline} clips={clips} currentTime={0} onSeek={seek} video set={set} previews={previews} />);
  const slider = screen.getByRole('slider');
  slider.getBoundingClientRect = () => ({ left: 100, width: 200 });
  fireEvent.pointerMove(slider, { clientX: 200 });
  expect(screen.getByRole('img', { name: 'Video preview at 0:50' })).toBeInTheDocument();
  expect(view.container.querySelector('.cs-scrub-sprite')).toHaveStyle({ backgroundImage: 'url("blob:cached")' });
  expect(seek).not.toHaveBeenCalled();
  fireEvent.pointerLeave(slider);
  expect(screen.queryByRole('img')).toBeNull();
  fireEvent.focus(slider);
  fireEvent.change(slider, { target: { value: '60' } });
  expect(screen.getByRole('img', { name: 'Video preview at 1:00' })).toBeInTheDocument();
  expect(seek).toHaveBeenLastCalledWith(60);
  fireEvent.blur(slider);
  expect(screen.queryByRole('img')).toBeNull();
  vi.unstubAllGlobals();
});

it('identifies the new source when a frame boundary is rounded to browser microseconds', () => {
  const boundary = 1039 + 2 / 24;
  const { container } = render(<MixTimeline timeline={{ duration: 1200, segments: [
    { clip_id: 'a', start: 0, end: boundary }, { clip_id: 'b', start: boundary, end: 1200 },
  ] }} clips={clips} currentTime={1039.083333} onSeek={() => {}} video />);
  expect(container.querySelector('.cs-timeline-detail')).toHaveTextContent(/^Balcony.mp4$/);
});
