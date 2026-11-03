import React from 'react';

const WIDTHS = ['62%', '48%', '56%', '40%', '52%'];

// Placeholder rows shaped like the list they stand in for. They fade in after a
// short delay, so a quick response replaces them before they are ever seen.
export default function LoadingRows({ rows = 3, avatar = true, label = 'Loading…', className = '' }) {
  return (
    <div role="status" aria-label={label} className={`jk-skeleton-rows ${className}`}>
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="jk-skeleton-row" aria-hidden="true">
          {avatar && <span className="jk-skeleton jk-skeleton-avatar" />}
          <span className="jk-skeleton jk-skeleton-line" style={{ width: WIDTHS[index % WIDTHS.length] }} />
          <span className="jk-skeleton jk-skeleton-value" />
        </div>
      ))}
    </div>
  );
}

export function LoadingPage({ label = 'Loading…', width = 'max-w-2xl' }) {
  return (
    <div className={`${width} mx-auto px-4 sm:px-6 py-8`}>
      <div role="status" aria-label={label} className="jk-skeleton-page">
        <span className="jk-skeleton jk-skeleton-title" aria-hidden="true" />
        <div className="jk-card overflow-hidden" aria-hidden="true">
          <LoadingRows rows={4} label={label} />
        </div>
      </div>
    </div>
  );
}
