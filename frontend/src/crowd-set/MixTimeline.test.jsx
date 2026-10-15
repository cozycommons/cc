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

it('renders one proportional strip from selected segments with source links, gaps and fades', () => {
  const { container } = render(<MixTimeline timeline={timeline} clips={clips} currentTime={75} onSeek={() => {}} />);
  expect(container.querySelectorAll('svg')).toHaveLength(1);
  const segments = container.querySelectorAll('rect > title');
  expect(segments).toHaveLength(3);
  expect(segments[0].parentElement).toHaveAttribute('width', '400');
  expect(segments[1].parentElement).toHaveAttribute('x', '399.2');
  expect(segments[1].parentElement).toHaveAttribute('fill', recordingColor('b', clips));
  expect(recordingColor('a', clips)).not.toBe(recordingColor('b', clips));
  expect(screen.getByRole('link', { name: 'Stage.mp4' })).toHaveAttribute('href', '#recording-a');
  expect(screen.queryByRole('link', { name: 'Unselected.mp4' })).not.toBeInTheDocument();
  expect(screen.getAllByText('Silence')).toHaveLength(2);
  expect(screen.getByText('Striped edge: crossfade')).toBeInTheDocument();
  expect(screen.getByRole('slider', { name: 'Seek mix' })).toHaveAttribute('aria-valuetext', '1:15 of 1:40');
});

it('seeks within the full duration and identifies both sources during a crossfade', () => {
  const seek = vi.fn();
  render(<MixTimeline timeline={timeline} clips={clips} currentTime={39.95} onSeek={seek} />);
  expect(screen.getByText('Stage.mp4 + Balcony.mp4 · Crossfade')).toBeInTheDocument();
  fireEvent.change(screen.getByRole('slider'), { target: { value: '82.5' } });
  expect(seek).toHaveBeenCalledWith(82.5);
});
