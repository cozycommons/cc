import React from 'react';

const phases = [
  ['prepare', 'Prepare clips'], ['align', 'Match recordings'], ['audio', 'Mix audio'],
  ['render', 'Render video'], ['finalize', 'Finish cut'], ['save', 'Save'],
];

function duration(seconds, roundUp = true) {
  const minutes = roundUp ? Math.ceil(seconds / 60) : Math.floor(seconds / 60);
  if (minutes < 1) return '<1 min';
  return minutes < 60 ? `${minutes} min` : `${Math.floor(minutes / 60)} hr ${minutes % 60} min`;
}

export default function ProcessingStatus({ set }) {
  const progress = set.processing;
  const current = phases.findIndex(([phase]) => phase === progress?.phase);
  const elapsed = progress?.started_at ? Math.max(0, Date.now() / 1000 - progress.started_at) : null;
  const measured = progress?.phase === 'render' && Number.isFinite(progress.percent);
  const quiet = measured && progress.updated_at && Date.now() / 1000 - progress.updated_at > 120;
  return <div className="cs-processing" aria-label="Processing progress">
    <div className="cs-processing-heading">
      <p role="status">{set.stage || 'Starting processing…'}</p>
      {measured && <strong>{progress.percent}%</strong>}
    </div>
    {measured && <progress aria-label="Video rendering" value={progress.percent} max="100" />}
    <ol className="cs-processing-steps" aria-label="Processing steps">
      {phases.map(([phase, label], index) => <li key={phase} aria-current={index === current ? 'step' : undefined}
        className={index < current ? 'cs-step-done' : ''}>{label}</li>)}
    </ol>
    <p className="cs-meta">
      {elapsed !== null && `${duration(elapsed, false)} elapsed`}
      {measured && !quiet && progress.remaining_seconds > 0 && ` · About ${duration(progress.remaining_seconds)} of video rendering left`}
    </p>
    {quiet && <p className="cs-meta">No new render progress in {duration(Date.now() / 1000 - progress.updated_at, false)}. Still checking…</p>}
    <p className="cs-meta">You can leave this page. Processing continues on the server.</p>
  </div>;
}
