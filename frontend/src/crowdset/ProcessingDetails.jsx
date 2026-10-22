import React from 'react';

export default function ProcessingDetails({ set }) {
  const progress = set.processing;
  const events = set.processing_events || [];
  return <details className="cs-processing-details">
    <summary>Processing details</summary>
    <dl>
      <dt>Status</dt><dd>{set.stage || set.status}</dd>
      {progress?.engine && <><dt>Renderer</dt><dd>{progress.engine === 'h264_nvenc' ? 'PC · NVIDIA GPU' : 'PC · CPU'}</dd></>}
      {progress?.total > 0 && <><dt>Frames</dt><dd>{Math.min(progress.completed || 0, progress.total).toLocaleString()} / {progress.total.toLocaleString()}</dd></>}
      {progress?.fps > 0 && <><dt>Speed</dt><dd>{progress.fps.toFixed(1)} fps · {(progress.fps / 24).toFixed(1)}× playback</dd></>}
      {progress?.updated_at > 0 && <><dt>Last progress</dt><dd>{new Date(progress.updated_at * 1000).toLocaleTimeString()}</dd></>}
    </dl>
    {events.length ? <ol aria-label="Processing events">{events.map((event, index) => <li key={`${event.at}-${index}`}>
      <time dateTime={new Date(event.at * 1000).toISOString()}>{new Date(event.at * 1000).toLocaleTimeString()}</time> {event.message}
    </li>)}</ol> : <p className="cs-meta">Events will appear as the worker reports progress.</p>}
  </details>;
}
