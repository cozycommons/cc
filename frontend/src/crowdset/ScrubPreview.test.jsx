import React from 'react';
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import ScrubPreview, { previewFrame, useScrubPreviews } from './ScrubPreview';

vi.mock('./api', () => ({ endpoint: (path) => `/crowdset/sets${path}` }));
const source = { interval: 10, start: 0, count: 60, columns: 5, rows: 10, sheets: ['first.jpg', 'second.jpg'] };
const set = { id: 'set', mix_revision: 'revision', scrub_previews: { official: source, friend: { ...source, start: -2, sheets: ['friend.jpg'] } },
  video_timeline: { segments: [{ clip_id: 'official', start: 0, end: 10, offset: 0 }, { clip_id: 'friend', start: 10, end: 20, offset: -10 }, { clip_id: 'official', start: 20, end: 600, offset: 0 }] } };
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it('resolves source timing, cut boundaries, sheet boundaries and missing previews', () => {
  expect(previewFrame(set, 9).src).toContain('first.jpg');
  expect(previewFrame(set, 10)).toEqual({ src: '/crowdset/sets/set/previews/friend.jpg?v=revision', size: '500% 1000%', position: '50% 0%' });
  expect(previewFrame(set, 20).src).toContain('first.jpg');
  expect(previewFrame(set, 499).position).toBe('100% 100%');
  expect(previewFrame(set, 500)).toEqual({ src: '/crowdset/sets/set/previews/second.jpg?v=revision', size: '500% 1000%', position: '0% 0%' });
  expect(previewFrame(set, 600)).toBeNull();
  expect(previewFrame({ ...set, scrub_previews: {} }, 5)).toBeNull();
});

it('updates a decoded sprite immediately without video, timers, or loading cards', () => {
  const loaded = new Map([[previewFrame(set, 20).src, 'blob:official'], [previewFrame(set, 10).src, 'blob:friend']]);
  const view = render(<ScrubPreview set={set} time={20} left="50%" label="0:20" loaded={loaded} />);
  expect(view.container.querySelector('.cs-scrub-sprite').style.backgroundPosition).toBe('50% 0%');
  view.rerender(<ScrubPreview set={set} time={30} left="60%" label="0:30" loaded={loaded} />);
  expect(view.container.querySelector('.cs-scrub-sprite').style.backgroundPosition).toBe('75% 0%');
  view.rerender(<ScrubPreview set={set} time={10} left="10%" label="0:10" loaded={loaded} />);
  expect(view.container.querySelector('.cs-scrub-sprite').style.backgroundImage).toContain('blob:friend');
  expect(view.container.querySelector('video')).toBeNull();
  view.rerender(<ScrubPreview set={set} time={500} left="80%" label="8:20" loaded={loaded} />);
  expect(view.container.querySelector('.cs-scrub-picture')).toBeNull();
  expect(screen.getByText('8:20')).toBeInTheDocument();
  expect(screen.queryByText(/Loading/)).toBeNull();
});

it('preloads on mount, waits for decoding, tolerates failure, and isolates changed revisions', async () => {
  const images = [];
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, blob: async () => new Blob(['jpeg']) })));
  vi.spyOn(URL, 'createObjectURL').mockImplementation(() => `blob:preview-${images.length}`);
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
  vi.stubGlobal('Image', class {
    constructor() {
      images.push(this);
      this.decode = vi.fn(() => new Promise((resolve, reject) => { this.finish = resolve; this.fail = reject; }));
    }
    set src(value) { this.url = value; }
  });
  function Fixture({ data }) {
    const loaded = useScrubPreviews(data);
    return <ScrubPreview set={data} time={20} left="10%" label="0:20" loaded={loaded} />;
  }
  const view = render(<Fixture data={set} />);
  await waitFor(() => expect(images).toHaveLength(3));
  expect(fetch).toHaveBeenCalledTimes(3);
  expect(view.container.querySelector('.cs-scrub-picture')).toBeNull();
  await act(async () => { images[0].finish(); images[1].fail(); images[2].finish(); });
  await waitFor(() => expect(view.container.querySelector('.cs-scrub-picture')).not.toBeNull());
  expect(images[0].decode).toHaveBeenCalledOnce();
  view.rerender(<Fixture data={{ ...set, mix_revision: 'new' }} />);
  expect(view.container.querySelector('.cs-scrub-picture')).toBeNull();
  expect(images[0].url).toBe('');
  await waitFor(() => expect(images).toHaveLength(6));
  expect(fetch.mock.calls[3][0]).toContain('?v=new');
  expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:preview-0');
  view.unmount();
  expect(images[3].url).toBe('');
});
