import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import CrowdSet from './CrowdSet';
import { request } from './api';

vi.mock('./api', () => ({ request: vi.fn(), endpoint: (path) => `/crowd-set/sets${path}` }));
const performance = { id: 'one', name: 'A night together', visibility: 'shared', can_manage: true, status: 'idle', clips: [], timeline: null, playable: false };
const clip = { id: 'clip', name: 'Stage.mp4', role: 'recording', kind: 'video', can_edit: true, included: true };
const ready = { ...performance, status: 'ready', playable: true, mix_revision: 'published', clips: [clip], timeline: { segments: [{ clip_id: clip.id }] } };
async function openSet() {
  fireEvent.click(await screen.findByRole('button', { name: /A night together/ }));
  return screen.findByRole('heading', { name: performance.name });
}
beforeEach(() => { request.mockReset(); });
afterEach(() => { cleanup(); vi.useRealTimers(); });

it('browses sets before opening a simple set detail', async () => {
  request.mockResolvedValueOnce([ready]);
  render(<CrowdSet />);
  await screen.findByRole('button', { name: /A night together/ });
  expect(screen.queryByLabelText('Current mix')).not.toBeInTheDocument();
  await openSet();
  expect(screen.getByLabelText('Current mix')).toBeInTheDocument();
  expect(screen.getByLabelText('Play Stage.mp4').tagName).toBe('VIDEO');
  expect(screen.getByLabelText('Play Stage.mp4')).toHaveAttribute('src', '/crowd-set/sets/one/clips/clip/media');
  expect(screen.getByText('In current mix')).toBeInTheDocument();
  expect(screen.queryByText(/reference|timing details|volume adjustments/i)).not.toBeInTheDocument();
  expect(screen.getByLabelText('Compiled mix').compareDocumentPosition(screen.getByLabelText('Recordings')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

it('creates a set, finds it in the catalog, opens it and uploads a video', async () => {
  const uploaded = { ...performance, status: 'queued', clips: [clip] };
  request.mockResolvedValueOnce([]).mockResolvedValueOnce(performance).mockResolvedValueOnce([performance]).mockResolvedValueOnce(uploaded);
  render(<CrowdSet />);
  fireEvent.click(await screen.findByRole('button', { name: 'New set' }));
  expect(screen.getByLabelText('New set')).toHaveFocus();
  expect(screen.getByRole('button', { name: 'Create set' })).toBeDisabled();
  fireEvent.change(screen.getByLabelText('New set'), { target: { value: `  ${performance.name}  ` } });
  fireEvent.click(screen.getByRole('button', { name: 'Create set' }));
  await screen.findByRole('heading', { name: performance.name });
  expect(JSON.parse(request.mock.calls[1][1].body)).toEqual({ name: performance.name });
  expect(screen.getByLabelText('Add videos')).toBeEnabled();
  expect(screen.getByText('No mix yet.')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: /All sets/ }));
  await openSet();
  const file = new File(['video'], clip.name, { type: 'video/mp4' });
  fireEvent.change(screen.getByLabelText('Add videos'), { target: { files: [file] } });
  await screen.findByText(clip.name);
  expect(request.mock.calls[3][0]).toBe('/one/clips?name=Stage.mp4');
  expect(request.mock.calls[3][1].body).toBe(file);
});

it('shows creation progress and keeps the name when creation fails', async () => {
  let reject;
  request.mockResolvedValueOnce([]).mockImplementationOnce(() => new Promise((resolve, fail) => { reject = fail; }));
  render(<CrowdSet />);
  fireEvent.change(await screen.findByLabelText('New set'), { target: { value: performance.name } });
  fireEvent.click(screen.getByRole('button', { name: 'Create set' }));
  expect(screen.getByRole('button', { name: 'Creating…' })).toBeDisabled();
  reject(new Error('Storage unavailable'));
  await screen.findByRole('alert');
  expect(screen.getByRole('alert')).toHaveTextContent('Storage unavailable');
  expect(screen.getByLabelText('New set')).toHaveValue(performance.name);
  expect(screen.getByRole('button', { name: 'Create set' })).toBeEnabled();
});

it('uploads directly and keeps the published player mounted while rebuilding', async () => {
  request.mockResolvedValueOnce([ready]).mockResolvedValueOnce({ ...ready, status: 'queued', dirty: true, clips: [clip, { ...clip, id: 'second', name: 'More.mp4' }] });
  render(<CrowdSet />);
  await openSet();
  const player = screen.getByLabelText('Current mix');
  const source = new File(['video'], 'More.mp4', { type: 'video/mp4' });
  fireEvent.change(screen.getByLabelText('Add videos'), { target: { files: [source] } });
  await screen.findByText('More.mp4');
  await screen.findByText('Mix queued…');
  expect(request.mock.calls[1][0]).toBe('/one/clips?name=More.mp4');
  expect(request.mock.calls[1][1].body).toBe(source);
  expect(screen.getByLabelText('Current mix')).toBe(player);
  expect(screen.getByLabelText('Current mix')).toHaveAttribute('src', '/crowd-set/sets/one/audio?v=published');
});

it('publishes one new player and keeps unmatched originals available', async () => {
  const unmatched = { ...clip, id: 'other', name: 'Other.mp4', can_edit: false, alignment: { status: 'unmatched' } };
  request.mockResolvedValueOnce([{ ...ready, status: 'processing' }]).mockResolvedValue({ ...ready, mix_revision: 'new', clips: [clip, unmatched] });
  render(<CrowdSet />);
  await openSet();
  await screen.findByText('Updating mix…');
  const before = screen.getByLabelText('Current mix');
  expect(screen.getByLabelText('Add videos')).toBeDisabled();
  await screen.findByText('Couldn’t match this recording.', {}, { timeout: 3000 });
  expect(screen.getByLabelText('Current mix')).not.toBe(before);
  expect(screen.getAllByLabelText('Current mix')).toHaveLength(1);
  expect(screen.getByLabelText('Play Other.mp4')).toBeInTheDocument();
  expect(screen.queryByLabelText('Use Other.mp4 in mix')).not.toBeInTheDocument();
});

it('keeps a failed previous mix and protects legacy originals from silent inclusion', async () => {
  const legacy = { ...clip, id: 'old', name: 'Older.wav', kind: 'audio', role: 'reference' };
  request.mockResolvedValueOnce([{ ...ready, status: 'failed', error: 'No usable recordings. Add a video with audible sound, then retry.', clips: [clip, legacy] }]);
  render(<CrowdSet />);
  await openSet();
  expect(screen.getByLabelText('Current mix')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Retry' })).toBeEnabled();
  expect(screen.getByLabelText('Play Older.wav').tagName).toBe('AUDIO');
  expect(screen.getByText('Original only')).toBeInTheDocument();
  expect(screen.queryByLabelText('Use Older.wav in mix')).not.toBeInTheDocument();
  fireEvent.error(screen.getByLabelText('Play Stage.mp4'));
  expect(screen.getByText('Can’t play this format here. Download the original below.')).toBeInTheDocument();
  await waitFor(() => expect(screen.getByRole('link', { name: 'Download audio' })).toBeInTheDocument());
});

it('finishes a batch once after every upload settles, including a partial failure', async () => {
  const held = { ...ready, status: 'uploading' };
  request.mockResolvedValueOnce([ready]).mockResolvedValueOnce({ id: 'batch' })
    .mockResolvedValueOnce(held).mockRejectedValueOnce(new Error('Connection lost'))
    .mockResolvedValueOnce(held).mockResolvedValueOnce({ ...ready, status: 'queued', dirty: true });
  render(<CrowdSet />);
  await openSet();
  const player = screen.getByLabelText('Current mix');
  fireEvent.change(screen.getByLabelText('Add videos'), { target: { files: ['One.mp4', 'Two.mp4', 'Three.mp4'].map((name) => new File(['video'], name)) } });
  await screen.findByRole('alert');
  expect(screen.getByRole('alert')).toHaveTextContent('Two.mp4: Connection lost');
  expect(screen.getByLabelText('Current mix')).toBe(player);
  expect(request.mock.calls.slice(1).map(([path]) => path)).toEqual([
    '/one/batches', '/one/clips?name=One.mp4&batch_id=batch', '/one/clips?name=Two.mp4&batch_id=batch',
    '/one/clips?name=Three.mp4&batch_id=batch', '/one/batches/batch/finish',
  ]);
  expect(screen.getByText('Mix queued…')).toBeInTheDocument();
});

it('connects the timeline seek and playhead to the current audio player', async () => {
  const timed = { ...ready, clips: [clip, { ...clip, id: 'other', name: 'Other.mp4', alignment: { status: 'matched' } }], timeline: { duration: 100, segments: [{ clip_id: clip.id, start: 0, end: 100, fade_in: 0 }], gaps: [] } };
  request.mockResolvedValueOnce([timed]);
  render(<CrowdSet />);
  await openSet();
  const audio = screen.getByLabelText('Current mix');
  fireEvent.change(screen.getByRole('slider', { name: 'Seek mix' }), { target: { value: '42' } });
  expect(audio.currentTime).toBe(42);
  expect(screen.getByText('Matched · not selected')).toBeInTheDocument();
  expect(screen.queryByRole('link', { name: 'Other.mp4' })).not.toBeInTheDocument();
  audio.currentTime = 63;
  fireEvent.timeUpdate(audio);
  expect(screen.getByRole('slider')).toHaveValue('63');
  expect(screen.getByRole('link', { name: 'Stage.mp4' })).toHaveAttribute('href', '#recording-clip');
});
