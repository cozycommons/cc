import React from 'react';
import { request } from './api';

export default function YouTubeImport({ set, disabled, onUpdate }) {
  const [url, setUrl] = React.useState('');
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState('');
  const job = set.youtube_import;

  async function submit(event) {
    event.preventDefault();
    setSubmitting(true); setError('');
    try {
      onUpdate(await request(`/${set.id}/youtube`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ url: url.trim() }),
      }));
      setUrl('');
    } catch (failure) { setError(failure.message); }
    finally { setSubmitting(false); }
  }

  return <div className="cs-youtube">
    <form onSubmit={submit}>
      <label htmlFor="youtube-url">Or add from YouTube</label>
      <div className="cs-youtube-fields">
        <input id="youtube-url" type="url" placeholder="https://youtu.be/…" value={url} maxLength={2048}
          disabled={disabled || submitting} onChange={(event) => setUrl(event.target.value)} required />
        <button type="submit" disabled={disabled || submitting || !url.trim()}>{submitting ? 'Adding…' : 'Add video'}</button>
      </div>
      <p className="cs-meta">One public video · up to 720p · same recording limits</p>
    </form>
    {(error || job?.state === 'failed') && <div role="alert" className="cs-error">
      {error || job.error}
      {!error && <button disabled={disabled || submitting} onClick={() => { setUrl(job.url); setError(''); }}>Use link again</button>}
    </div>}
  </div>;
}
