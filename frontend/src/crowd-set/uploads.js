import { request } from './api';

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const retryable = (error) => !error.status || [408, 409, 429, 500, 502, 503, 504].includes(error.status);

async function retry(callback) {
  for (let attempt = 0; ; attempt += 1) {
    try { return await callback(); }
    catch (error) {
      if (attempt >= 4 || !retryable(error)) throw error;
      await sleep(500 * 2 ** attempt);
    }
  }
}

async function hash(bytes) {
  const value = await crypto.subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(value), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

async function fingerprint(file) {
  const bytes = await new Blob([
    new TextEncoder().encode(`${file.name}:${file.size}:${file.lastModified || 0}:`),
    file.slice(0, 65536), file.slice(Math.max(0, file.size - 65536)),
  ]).arrayBuffer();
  return hash(bytes);
}

export async function uploadRecording(setId, file, { batchId, limits, onProgress = () => {} }) {
  if (!limits.resumable_uploads) {
    return request(`/${setId}/clips?name=${encodeURIComponent(file.name)}${batchId ? `&batch_id=${batchId}` : ''}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/octet-stream' }, body: file,
    });
  }
  const ownedBatch = !batchId;
  const batch = batchId || (await retry(() => request(`/${setId}/batches`, { method: 'POST' }))).id;
  let session;
  let result;
  let failure;
  try {
    const identity = await fingerprint(file);
    session = await retry(() => request(`/${setId}/uploads`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: file.name, size: file.size, fingerprint: identity, batch_id: batch }),
    }));
    while (session.state !== 'complete' && session.offset < file.size) {
      if (!Number.isInteger(session.offset) || session.offset < 0) throw new Error('Invalid saved upload offset. Reselect this file.');
      const offset = session.offset;
      const chunk = file.slice(offset, Math.min(file.size, offset + limits.chunk_bytes));
      const checksum = await hash(await chunk.arrayBuffer());
      session = await retry(async () => {
        const saved = await request(`/${setId}/uploads/${session.id}`);
        if (saved.offset !== offset) return saved;
        return request(`/${setId}/uploads/${session.id}?offset=${offset}&checksum=${checksum}`, {
          method: 'PATCH', headers: { 'Content-Type': 'application/octet-stream' }, body: chunk,
        });
      });
      if (session.offset > file.size) throw new Error('Saved upload exceeded the selected file size.');
      onProgress(session.offset, file.size);
    }
    onProgress(file.size, file.size);
    result = await retry(() => request(`/${setId}/uploads/${session.id}/finish`, { method: 'POST' }));
  } catch (error) {
    failure = error;
    if (session && [413, 415, 422].includes(error.status)) {
      await request(`/${setId}/uploads/${session.id}`, { method: 'DELETE' }).catch(() => {});
    }
  } finally {
    if (ownedBatch) {
      try { result = await retry(() => request(`/${setId}/batches/${batch}/finish`, { method: 'POST' })); }
      catch (error) { if (!failure) failure = error; }
    }
  }
  if (failure) throw failure;
  return result;
}
