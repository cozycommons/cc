import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import CrowdSet from './CrowdSet';
import { request } from './api';

vi.mock('./api', () => ({ request: vi.fn(), endpoint: (path) => `/crowd-set/sets${path}` }));
const performance = { id: 'one', name: 'A night together', status: 'idle', clips: [], timeline: null, playable: false };
const reference = { id: 'ref', name: 'Reference.mp4', role: 'reference', included: true };
const clip = { id: 'clip', name: 'Crowd.wav', role: 'crowd', included: true };
const view = () => render(<MemoryRouter><CrowdSet /></MemoryRouter>);
beforeEach(() => { request.mockReset(); });
afterEach(() => { cleanup(); vi.useRealTimers(); });

it('creates a performance and requires reference before processing', async () => {
  request.mockResolvedValueOnce([]).mockResolvedValueOnce(performance);
  view();
  await screen.findByLabelText('New set');
  fireEvent.change(screen.getByLabelText('New set'), { target: { value: performance.name } });
  fireEvent.click(screen.getByRole('button', { name: 'Create set' }));
  await screen.findByRole('heading', { name: performance.name });
  expect(screen.getByRole('button', { name: 'Create mix' })).toBeDisabled();
  expect(screen.getByText('Upload a reference to continue.')).toBeInTheDocument();
});

it('uploads files with explicit roles and supports source exclusion', async () => {
  request.mockResolvedValueOnce([performance])
    .mockResolvedValueOnce({ ...performance, clips: [reference] })
    .mockResolvedValueOnce({ ...performance, clips: [reference, clip] })
    .mockResolvedValueOnce({ ...performance, clips: [reference, { ...clip, included: false }] });
  view();
  const refInput = await screen.findByLabelText('Upload timing reference');
  const ref = new File(['abc'], 'Reference.mp4');
  fireEvent.change(refInput, { target: { files: [ref] } });
  await screen.findByText('Not included in playback');
  expect(request.mock.calls[1][0]).toContain('role=reference');
  const source = new File(['def'], 'Crowd.wav');
  fireEvent.change(screen.getByLabelText('Upload crowd clips'), { target: { files: [source] } });
  await screen.findByLabelText('Crowd.wav');
  await waitFor(() => expect(screen.getByRole('button', { name: 'Create mix' })).toBeEnabled());
  expect(request.mock.calls[2][1].body).toBe(source);
  fireEvent.click(screen.getByLabelText('Crowd.wav'));
  await screen.findByText('Excluded');
  expect(screen.getByRole('button', { name: 'Create mix' })).toBeDisabled();
});

it('polls progress into playback, renders gaps and unmatched explanations', async () => {
  const ready = { ...performance, status: 'ready', playable: true,
    clips: [reference, { ...clip, alignment: { status: 'unmatched', reason: 'Insufficient distinct matches.', windows: [] } }],
    timeline: { duration: 100, covered_seconds: 40, levels: { clip: { gain_db: -4.2, basis: 'Same 20.0s overlapping passage', gain_limited: false } }, segments: [{ clip_id: 'other', start: 20, end: 60, fade_in: 0 }], gaps: [{ start: 0, end: 20 }, { start: 60, end: 100 }] } };
  request.mockResolvedValueOnce([{ ...performance, clips: [reference, clip], status: 'processing', stage: 'Analyzing reference timing' }]).mockResolvedValue(ready);
  view();
  await screen.findByText('Processing recordings…');
  expect(screen.getByRole('button', { name: 'Processing…' })).toBeDisabled();
  await screen.findByLabelText('Crowd-only reconstruction', {}, { timeout: 3000 });
  expect(screen.getByText('0:00.0–0:20.0 · silence')).toBeInTheDocument();
  expect(screen.getByText('Insufficient distinct matches.')).toBeInTheDocument();
  expect(screen.getByText('Volume adjustments')).toBeInTheDocument();
  expect(screen.getByText(/overlap matched/)).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Download WAV' })).toHaveAttribute('href', '/crowd-set/sets/one/audio?download=true');
});

it('shows reconnect and recoverable worker failures', async () => {
  request.mockRejectedValueOnce(new Error('Failed to fetch')).mockResolvedValueOnce([{ ...performance, status: 'failed', clips: [reference, clip], error: 'Audio conversion exceeded the 3 minute limit.' }]);
  view();
  fireEvent.click(await screen.findByRole('button', { name: 'Reconnect' }));
  await screen.findByText('Audio conversion exceeded the 3 minute limit.');
  expect(screen.getByRole('button', { name: 'Retry' })).toBeEnabled();
});
