import React from 'react';
import { cleanup, fireEvent, render as renderUI, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import Crowdset from './Crowdset';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
const render = (node) => renderUI(<BrowserRouter><Routes><Route path="/crowdset/:slug?" element={node} /></Routes></BrowserRouter>);
import { request } from './api';
import { auth } from '../supabase';
vi.mock('../supabase', () => ({ auth: { signInWithGoogle: vi.fn() } }));

vi.mock('./api', () => ({ request: vi.fn(), getLimits: async () => ({ recordings: 64, file_bytes: 2 * 1024 ** 3, recording_seconds: 7200, youtube_imports: true }), endpoint: (path) => `/crowdset/sets${path}` }));
const performance = { id: 'one', slug: 'a-night-together', name: 'A night together', visibility: 'shared', can_manage: true, can_delete: true, status: 'idle', clips: [], timeline: null, playable: false };
const clip = { id: 'clip', name: 'Stage.mp4', role: 'recording', kind: 'video', can_edit: true, can_delete: true, included: true };
const ready = { ...performance, status: 'ready', playable: true, mix_revision: 'published', clips: [clip], timeline: { segments: [{ clip_id: clip.id }] } };
async function openSet() {
  fireEvent.click(await screen.findByRole('link', { name: /A night together/ }));
  return screen.findByRole('heading', { name: performance.name });
}
beforeEach(() => { request.mockReset(); window.history.replaceState({}, '', '/crowdset'); });
afterEach(() => { cleanup(); vi.useRealTimers(); });

it('browses sets before opening a simple set detail', async () => {
  request.mockResolvedValueOnce([ready]);
  render(<Crowdset />);
  await screen.findByRole('link', { name: /A night together/ });
  expect(screen.queryByLabelText('Current mix')).not.toBeInTheDocument();
  await openSet();
  expect(screen.getByLabelText('Current mix')).toBeInTheDocument();
  expect(screen.getByLabelText('Play Stage.mp4').tagName).toBe('VIDEO');
  expect(screen.getByLabelText('Play Stage.mp4')).toHaveAttribute('src', '/crowdset/sets/one/clips/clip/media');
  expect(screen.getByText('In current mix')).toBeInTheDocument();
  expect(screen.queryByText(/reference|timing details|volume adjustments/i)).not.toBeInTheDocument();
  expect(screen.getByLabelText('Compiled mix').compareDocumentPosition(screen.getByLabelText('Recordings')) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

it('accepts fifty friends plus a released recording and does not preload every original', async () => {
  const clips = Array.from({ length: 51 }, (_, index) => ({ ...clip, id: `clip-${index}`, name: `Friend ${index}.mp4` }));
  request.mockResolvedValueOnce([{ ...ready, clips }]);
  render(<Crowdset />);
  await openSet();
  expect(screen.getByLabelText('Add clips')).toBeEnabled();
  expect(screen.getByText(/Up to 64 clips/)).toBeInTheDocument();
  expect(screen.getByLabelText('Play Friend 50.mp4')).toHaveAttribute('preload', 'none');
});

it('creates a set, finds it in the catalog, opens it and uploads a video', async () => {
  const uploaded = { ...performance, status: 'queued', clips: [clip] };
  request.mockResolvedValueOnce([]).mockResolvedValueOnce(performance).mockResolvedValueOnce([performance]).mockResolvedValueOnce(uploaded);
  render(<Crowdset />);
  fireEvent.click(await screen.findByRole('button', { name: 'New set' }));
  expect(screen.getByLabelText('Set name')).toHaveFocus();
  expect(screen.getByRole('button', { name: 'Create set' })).toBeDisabled();
  fireEvent.change(screen.getByLabelText('Set name'), { target: { value: `  ${performance.name}  ` } });
  fireEvent.click(screen.getByRole('button', { name: 'Create set' }));
  await screen.findByRole('heading', { name: performance.name });
  expect(JSON.parse(request.mock.calls[1][1].body)).toEqual({ name: performance.name });
  expect(screen.getByLabelText('Add clips')).toBeEnabled();
  expect(screen.getByText('No clips yet.')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: /All sets/ }));
  await openSet();
  const file = new File(['video'], clip.name, { type: 'video/mp4' });
  fireEvent.change(screen.getByLabelText('Add clips'), { target: { files: [file] } });
  await screen.findByText(clip.name);
  expect(request.mock.calls[3][0]).toBe('/one/clips?name=Stage.mp4');
  expect(request.mock.calls[3][1].body).toBe(file);
});

it('shows creation progress and keeps the name when creation fails', async () => {
  let reject;
  request.mockResolvedValueOnce([]).mockImplementationOnce(() => new Promise((resolve, fail) => { reject = fail; }));
  render(<Crowdset />);
  fireEvent.click(await screen.findByRole('button', { name: 'New set' }));
  fireEvent.change(await screen.findByLabelText('Set name'), { target: { value: performance.name } });
  fireEvent.click(screen.getByRole('button', { name: 'Create set' }));
  expect(screen.getByRole('button', { name: 'Creating…' })).toBeDisabled();
  reject(new Error('Storage unavailable'));
  await screen.findByRole('alert');
  expect(screen.getByRole('alert')).toHaveTextContent('Storage unavailable');
  expect(screen.getByLabelText('Set name')).toHaveValue(performance.name);
  expect(screen.getByRole('button', { name: 'Create set' })).toBeEnabled();
});

it('uploads directly and keeps the published player mounted while rebuilding', async () => {
  request.mockResolvedValueOnce([ready]).mockResolvedValueOnce({ ...ready, status: 'queued', dirty: true, clips: [clip, { ...clip, id: 'second', name: 'More.mp4' }] });
  render(<Crowdset />);
  await openSet();
  const player = screen.getByLabelText('Current mix');
  const source = new File(['video'], 'More.mp4', { type: 'video/mp4' });
  fireEvent.change(screen.getByLabelText('Add clips'), { target: { files: [source] } });
  await screen.findByText('More.mp4');
  await screen.findByText('Queued for processing. Your recordings are saved.');
  expect(request.mock.calls[1][0]).toBe('/one/clips?name=More.mp4');
  expect(request.mock.calls[1][1].body).toBe(source);
  expect(screen.getByLabelText('Current mix')).toBe(player);
  expect(screen.getByLabelText('Current mix')).toHaveAttribute('src', '/crowdset/sets/one/audio?v=published');
});

it('publishes one new player and keeps unmatched originals available', async () => {
  const unmatched = { ...clip, id: 'other', name: 'Other.mp4', can_edit: false, alignment: { status: 'unmatched' } };
  request.mockResolvedValueOnce([{ ...ready, status: 'processing' }]).mockResolvedValue({ ...ready, mix_revision: 'new', clips: [clip, unmatched] });
  render(<Crowdset />);
  await openSet();
  await screen.findByText('Starting processing…');
  const before = screen.getByLabelText('Current mix');
  expect(screen.getByLabelText('Add clips')).toBeDisabled();
  await screen.findByText('Couldn’t match this recording.', {}, { timeout: 3000 });
  expect(screen.getByLabelText('Current mix')).not.toBe(before);
  expect(screen.getAllByLabelText('Current mix')).toHaveLength(1);
  expect(screen.getByLabelText('Play Other.mp4')).toBeInTheDocument();
  expect(screen.queryByLabelText('Use Other.mp4 in mix')).not.toBeInTheDocument();
});

it('keeps a failed previous mix and protects legacy originals from silent inclusion', async () => {
  const legacy = { ...clip, id: 'old', name: 'Older.wav', kind: 'audio', role: 'reference' };
  request.mockResolvedValueOnce([{ ...ready, status: 'failed', error: 'No usable recordings. Add a video with audible sound, then retry.', clips: [clip, legacy] }]);
  render(<Crowdset />);
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
  render(<Crowdset />);
  await openSet();
  const player = screen.getByLabelText('Current mix');
  fireEvent.change(screen.getByLabelText('Add clips'), { target: { files: ['One.mp4', 'Two.mp4', 'Three.mp4'].map((name) => new File(['video'], name)) } });
  await screen.findByRole('alert');
  expect(screen.getByRole('alert')).toHaveTextContent('Two.mp4: Connection lost');
  expect(screen.getByLabelText('Current mix')).toBe(player);
  expect(request.mock.calls.slice(1).map(([path]) => path)).toEqual([
    '/one/batches', '/one/clips?name=One.mp4&batch_id=batch', '/one/clips?name=Two.mp4&batch_id=batch',
    '/one/clips?name=Three.mp4&batch_id=batch', '/one/batches/batch/finish',
  ]);
  expect(screen.getByText('Queued for processing. Your recordings are saved.')).toBeInTheDocument();
  request.mockResolvedValueOnce(ready);
  fireEvent.click(screen.getByRole('button', { name: 'Retry 1 upload' }));
  await waitFor(() => expect(screen.queryByRole('button', { name: 'Retry 1 upload' })).not.toBeInTheDocument());
  expect(request.mock.calls[6][0]).toBe('/one/clips?name=Two.mp4');
});

it('connects the timeline seek and playhead to the current audio player', async () => {
  const timed = { ...ready, clips: [clip, { ...clip, id: 'other', name: 'Other.mp4', alignment: { status: 'matched' } }], timeline: { duration: 100, segments: [{ clip_id: clip.id, start: 0, end: 100, fade_in: 0 }], gaps: [] } };
  request.mockResolvedValueOnce([timed]);
  render(<Crowdset />);
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

it('uses one revision-pinned video player and preserves it during processing', async () => {
  const cut = { ...ready, video_playable: true, video_timeline: ready.timeline };
  request.mockResolvedValueOnce([cut]).mockResolvedValueOnce({ ...cut, status: 'queued', dirty: true, clips: [clip, { ...clip, id: 'second', name: 'More.mp4' }] });
  render(<Crowdset />);
  fireEvent.click(await screen.findByRole('link', { name: /Watch/ }));
  const video = screen.getByLabelText('Current cut');
  expect(video.tagName).toBe('VIDEO');
  expect(video).toHaveAttribute('src', '/crowdset/sets/one/video?v=published');
  expect(screen.queryByLabelText('Current mix')).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Add clips'), { target: { files: [new File(['video'], 'More.mp4', { type: 'video/mp4' })] } });
  await screen.findByText('Queued for processing. Your recordings are saved.');
  expect(screen.getByLabelText('Current cut')).toBe(video);
  expect(screen.getByRole('link', { name: 'Download video' })).toHaveAttribute('href', '/crowdset/sets/one/video?download=true&v=published');
});

it('imports a YouTube link and preserves the current player while downloading', async () => {
  const importing = { ...ready, status: 'importing', youtube_import: { state: 'downloading', stage: 'Downloading from YouTube · 42%…' } };
  request.mockResolvedValueOnce([ready]).mockResolvedValueOnce(importing);
  render(<Crowdset />);
  await openSet();
  const player = screen.getByLabelText('Current mix');
  fireEvent.change(screen.getByLabelText('Or add from YouTube'), { target: { value: 'https://youtu.be/9dhFH_G5Bow' } });
  fireEvent.click(screen.getByRole('button', { name: 'Add video' }));
  await screen.findByText('Downloading from YouTube · 42%…');
  expect(request.mock.calls[1][0]).toBe('/one/youtube');
  expect(JSON.parse(request.mock.calls[1][1].body)).toEqual({ url: 'https://youtu.be/9dhFH_G5Bow' });
  expect(screen.getByLabelText('Current mix')).toBe(player);
  expect(screen.getByLabelText('Add clips')).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Add video' })).toBeDisabled();
});

it('lets an interrupted YouTube import reuse its link without losing the cut', async () => {
  request.mockResolvedValueOnce([{ ...ready, youtube_import: { state: 'failed', url: 'https://www.youtube.com/watch?v=9dhFH_G5Bow', error: 'Import interrupted. Retry.' } }]);
  render(<Crowdset />);
  await openSet();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  fireEvent.click(screen.getByText('Previous YouTube import failed'));
  expect(screen.getByText('Import interrupted. Retry.')).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'Use link again' }));
  expect(screen.getByLabelText('Or add from YouTube')).toHaveValue('https://www.youtube.com/watch?v=9dhFH_G5Bow');
  expect(screen.getByRole('button', { name: 'Add video' })).toBeEnabled();
  expect(screen.getByLabelText('Current mix')).toBeInTheDocument();
});

it('lets the owner select official audio and labels the base download separately', async () => {
  const updated = { ...ready, soundtrack_clip_id: clip.id, status: 'queued' };
  request.mockResolvedValueOnce([ready]).mockResolvedValueOnce(updated);
  render(<Crowdset />);
  await openSet();
  fireEvent.click(screen.getByRole('button', { name: 'Use as official set' }));
  await screen.findByText('Official set audio');
  expect(request).toHaveBeenLastCalledWith('/one/soundtrack', expect.objectContaining({
    method: 'PUT', body: JSON.stringify({ clip_id: clip.id }),
  }));
  expect(screen.getByRole('button', { name: 'Clear official audio' })).toBeInTheDocument();
});


it('explains why a clip could not be matched without hiding the original', async () => {
  const reason = 'Several moments sound alike. Could not choose a reliable match.';
  request.mockResolvedValueOnce([{ ...performance, clips: [{ ...clip, alignment: { status: 'unmatched', reason } }] }]);
  render(<Crowdset />);
  await openSet();
  expect(screen.getByText(reason)).toBeInTheDocument();
  expect(screen.getByLabelText('Play Stage.mp4')).toBeInTheDocument();
});


it('retries unmatched clips while preserving the published player', async () => {
  const state = { ...ready, clips: [clip, { ...clip, id: 'unmatched', alignment: { status: 'unmatched' } }] };
  request.mockResolvedValueOnce([state]).mockResolvedValueOnce({ ...state, status: 'queued' });
  render(<Crowdset />);
  await openSet();
  const player = screen.getByLabelText('Current mix');
  fireEvent.click(screen.getByRole('button', { name: 'Retry matching' }));
  await waitFor(() => expect(request).toHaveBeenCalledWith('/one/process', { method: 'POST' }));
  expect(screen.getByLabelText('Current mix')).toBe(player);
});

it('opens a dedicated set URL directly and preserves it when reconnecting', async () => {
  window.history.replaceState({}, '', '/crowdset/a-night-together#recording-clip');
  request.mockResolvedValue([ready]);
  render(<Crowdset />);
  expect(await screen.findByLabelText('Current mix')).toBeInTheDocument();
  expect(document.title).toBe('A night together · Crowdset');
  expect(window.location.pathname).toBe('/crowdset/a-night-together');
});

it('uses real catalog links and browser Back returns to the catalog', async () => {
  request.mockResolvedValue([ready]);
  render(<Crowdset />);
  const link = await screen.findByRole('link', { name: /A night together/ });
  expect(link).toHaveAttribute('href', '/crowdset/a-night-together');
  fireEvent.click(link);
  await screen.findByLabelText('Current mix');
  window.history.back();
  await screen.findByRole('heading', { name: 'Sets', exact: true });
  expect(window.location.pathname).toBe('/crowdset');
});

it('canonicalizes ID links and gives inaccessible slugs a useful fallback', async () => {
  window.history.replaceState({}, '', '/crowdset/one#recording-clip');
  request.mockResolvedValue([ready]);
  const view = render(<Crowdset />);
  await screen.findByLabelText('Current mix');
  await waitFor(() => expect(window.location.pathname).toBe('/crowdset/a-night-together'));
  expect(window.location.hash).toBe('#recording-clip');
  view.unmount();
  window.history.replaceState({}, '', '/crowdset/not-visible');
  render(<Crowdset />);
  await screen.findByRole('heading', { name: 'Set unavailable' });
  expect(screen.queryByLabelText('Current mix')).not.toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Browse sets' })).toHaveAttribute('href', '/crowdset');
});

it('places downloads below the video and edit timeline', async () => {
  request.mockResolvedValue([{ ...ready, video_playable: true, video_timeline: { duration: 120, segments: [{ clip_id: clip.id, start: 0, end: 120 }] } }]);
  render(<Crowdset />);
  await openSet();
  const downloads = screen.getByLabelText('Downloads');
  expect(screen.getByLabelText('Video player').compareDocumentPosition(downloads) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(screen.getByRole('slider', { name: 'Seek mix' }).compareDocumentPosition(downloads) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});


it('keeps the dedicated set path as the sign-in destination', async () => {
  window.history.replaceState({}, '', '/crowdset/a-night-together');
  request.mockRejectedValue(Object.assign(new Error('Sign in'), { status: 401 }));
  render(<Crowdset />);
  fireEvent.click(await screen.findByRole('button', { name: 'Continue with Google' }));
  await waitFor(() => expect(auth.signInWithGoogle).toHaveBeenCalledWith(`${window.location.origin}/crowdset/a-night-together`));
});

it('collapses unused clips with preview posters and omits file sizes', async () => {
  const unused = { ...clip, id: 'unused', name: 'Back of crowd.mov', bytes: 123456789, alignment: { status: 'unmatched' } };
  request.mockResolvedValueOnce([{ ...ready, clips: [clip, unused] }]);
  render(<Crowdset />);
  await openSet();
  const preview = screen.getByLabelText('Play Back of crowd.mov');
  const section = preview.closest('details');
  expect(section).not.toHaveAttribute('open');
  expect(section.querySelector('summary')).toHaveTextContent('Not in the set 1');
  expect(preview).toHaveAttribute('poster', '/crowdset/sets/one/clips/unused/thumbnail');
  expect(preview).toHaveAttribute('preload', 'none');
  expect(preview.closest('article')).not.toHaveTextContent('MB');
  expect(screen.getByLabelText('Play Stage.mp4').closest('details')).toBeNull();
});

it('pauses other recordings while preserving the two synchronized cut videos', async () => {
  request.mockResolvedValueOnce([{ ...ready, video_playable: true, video_timeline: { duration: 20, segments: [{ clip_id: clip.id, asset_id: 'asset', start: 0, end: 10 }] } }]);
  render(<Crowdset />);
  await openSet();
  const base = screen.getByLabelText('Current cut');
  const companion = screen.getByLabelText('Friend’s picture');
  const original = screen.getByLabelText('Play Stage.mp4');
  [base, companion, original].forEach((media) => { media.pause = vi.fn(); });
  fireEvent.play(base);
  expect(original.pause).toHaveBeenCalledOnce();
  expect(companion.pause).not.toHaveBeenCalled();
  fireEvent.play(companion);
  expect(base.pause).not.toHaveBeenCalled();
  expect(original.pause).toHaveBeenCalledOnce();
  fireEvent.play(original);
  expect(base.pause).toHaveBeenCalledOnce();
  expect(companion.pause).toHaveBeenCalledOnce();
});

it('reports duplicate uploads without adding another card', async () => {
  request.mockResolvedValueOnce([ready]).mockResolvedValueOnce({ ...ready, duplicate_clip_id: clip.id });
  render(<Crowdset />);
  await openSet();
  fireEvent.change(screen.getByLabelText('Add clips'), { target: { files: [new File(['video'], 'renamed.mp4', { type: 'video/mp4' })] } });
  expect(await screen.findByText('1 duplicate skipped — already in this set.')).toBeInTheDocument();
  expect(screen.getAllByLabelText('Play Stage.mp4')).toHaveLength(1);
});


it('shows the uploader on compact cards without a duration or timeline heading', async () => {
  request.mockResolvedValueOnce([{ ...ready, clips: [{ ...clip, uploader_name: 'Jason Keung', duration: 5503.3 }], timeline: { ...ready.timeline, duration: 5503.3 } }]);
  render(<Crowdset />);
  await openSet();
  expect(screen.getByText('Uploaded by Jason Keung')).toBeInTheDocument();
  expect(screen.getByLabelText('Play Stage.mp4').closest('article')).not.toHaveTextContent('91:43.3');
  expect(screen.queryByText('Clip timeline')).not.toBeInTheDocument();
  expect(screen.getByRole('slider', { name: 'Seek mix' })).toBeInTheDocument();
});


it('hides set deletion from regular owners and permits removal only of their own clips', async () => {
  const other = { ...clip, id: 'other', name: 'Other.mp4', can_edit: true, can_delete: false };
  request.mockResolvedValueOnce([{ ...ready, can_manage: true, can_delete: false, clips: [clip, other] }]);
  render(<Crowdset />);
  await openSet();
  expect(screen.queryByRole('region', { name: 'Admin controls' })).not.toBeInTheDocument();
  expect(screen.queryByRole('button', { name: 'Delete set' })).not.toBeInTheDocument();
  expect(screen.getAllByRole('button', { name: 'Remove' })).toHaveLength(1);
  expect(screen.getByRole('button', { name: 'Remove' }).closest('article')).toHaveTextContent('Stage.mp4');
});

it('shows admin deletion controls even when the admin does not own the set or clips', async () => {
  request.mockResolvedValueOnce([{ ...ready, can_manage: false, can_delete: true, clips: [{ ...clip, can_edit: false, can_delete: true }] }]);
  render(<Crowdset />);
  await openSet();
  expect(screen.getByRole('region', { name: 'Admin controls' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Delete set' })).toBeEnabled();
  expect(screen.getByRole('button', { name: 'Remove' })).toBeEnabled();
  expect(screen.queryByRole('button', { name: 'Use as official set' })).not.toBeInTheDocument();
});

it('lets an admin prepare missing previews without replacing the published player', async () => {
  const video = { ...ready, can_delete: true, video_playable: true, video_timeline: { duration: 20, segments: [{ clip_id: clip.id, start: 0, end: 20, offset: 0 }] } };
  request.mockResolvedValueOnce([video]).mockResolvedValueOnce({ ...video, status: 'processing' });
  render(<Crowdset />);
  await openSet();
  const player = screen.getByLabelText('Current cut');
  fireEvent.click(screen.getByRole('button', { name: 'Prepare video previews' }));
  await screen.findByText('Starting processing…');
  expect(request).toHaveBeenLastCalledWith('/one/process', { method: 'POST' });
  expect(screen.getByLabelText('Current cut')).toBe(player);
});
