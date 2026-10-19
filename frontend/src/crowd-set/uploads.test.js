import { Blob, File } from 'node:buffer';
import { webcrypto } from 'node:crypto';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { request } from './api';
import { uploadRecording } from './uploads';

vi.mock('./api', () => ({ request: vi.fn() }));

beforeEach(() => {
  request.mockReset();
  vi.stubGlobal('Blob', Blob);
  vi.stubGlobal('crypto', webcrypto);
});
afterEach(() => vi.unstubAllGlobals());

it('resumes from the saved offset and recovers a lost chunk acknowledgment without duplicate bytes', async () => {
  const file = new File(['abcdef'], 'Clip.wav', { lastModified: 1 });
  let offset = 2;
  let lost = false;
  const appended = [];
  request.mockImplementation(async (path, options = {}) => {
    if (path === '/set/batches') return { id: 'batch' };
    if (path === '/set/uploads') return { id: 'upload', offset, state: 'uploading' };
    if (path === '/set/uploads/upload') return { id: 'upload', offset, state: 'uploading' };
    if (options.method === 'PATCH') {
      const params = new URLSearchParams(path.split('?')[1]);
      expect(Number(params.get('offset'))).toBe(offset);
      expect(params.get('checksum')).toMatch(/^[a-f0-9]{64}$/);
      const bytes = await options.body.text();
      appended.push(bytes);
      offset += bytes.length;
      if (!lost) { lost = true; throw Object.assign(new Error('Lost reply'), { status: 503 }); }
      return { id: 'upload', offset, state: 'uploading' };
    }
    if (path.endsWith('/finish')) return { id: 'set', clips: ['one recording'] };
    throw new Error(`Unexpected request: ${path}`);
  });
  const progress = vi.fn();
  const result = await uploadRecording('set', file, { limits: { resumable_uploads: true, chunk_bytes: 2 }, onProgress: progress });
  expect(appended).toEqual(['cd', 'ef']);
  expect(result.clips).toHaveLength(1);
  expect(progress).toHaveBeenLastCalledWith(6, 6);
  expect(request.mock.calls.filter(([path]) => path === '/set/batches/batch/finish')).toHaveLength(1);
});

it('keeps a caller batch open and finalizes an already completed session idempotently', async () => {
  const file = new File(['abc'], 'Clip.wav');
  request.mockImplementation(async (path) => path === '/set/uploads' ? { id: 'upload', offset: 3, state: 'complete' } : { id: 'set' });
  await uploadRecording('set', file, { batchId: 'batch', limits: { resumable_uploads: true, chunk_bytes: 2 } });
  expect(request.mock.calls.map(([path]) => path)).toEqual(['/set/uploads', '/set/uploads/upload/finish']);
});

it('retains transiently failed uploads for resumption and settles its batch', async () => {
  const file = new File(['abc'], 'Clip.wav');
  request.mockImplementation(async (path) => {
    if (path.endsWith('/batches')) return { id: 'batch' };
    if (path.endsWith('/uploads')) return { id: 'upload', offset: 0, state: 'uploading' };
    if (path.endsWith('/batches/batch/finish')) return { id: 'set' };
    throw Object.assign(new Error('Sign in again'), { status: 401 });
  });
  await expect(uploadRecording('set', file, { limits: { resumable_uploads: true, chunk_bytes: 2 } })).rejects.toThrow('Sign in again');
  expect(request.mock.calls.some(([, options]) => options?.method === 'DELETE')).toBe(false);
  expect(request.mock.calls.at(-1)[0]).toBe('/set/batches/batch/finish');
});
