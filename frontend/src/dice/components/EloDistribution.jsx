import React from 'react';

const BUCKET_SIZE = 25;

export function summarizeRatings(entries) {
  const ratings = (entries || [])
    .filter((entry) => !entry.is_provisional && Number.isFinite(entry.elo_rating))
    .map((entry) => entry.elo_rating);
  if (!ratings.length) return null;

  const mean = ratings.reduce((sum, rating) => sum + rating, 0) / ratings.length;
  const variance = ratings.reduce((sum, rating) => sum + ((rating - mean) ** 2), 0) / ratings.length;
  const deviation = Math.max(BUCKET_SIZE, Math.sqrt(variance));
  const minimum = Math.floor(Math.min(...ratings) / BUCKET_SIZE) * BUCKET_SIZE;
  const maximum = Math.ceil(Math.max(...ratings) / BUCKET_SIZE) * BUCKET_SIZE;
  const bucketCount = Math.max(1, Math.round((maximum - minimum) / BUCKET_SIZE) + 1);
  const buckets = Array.from({ length: bucketCount }, (_, index) => ({
    lower: minimum + (index * BUCKET_SIZE),
    count: 0,
  }));
  ratings.forEach((rating) => {
    const index = Math.min(buckets.length - 1, Math.floor((rating - minimum) / BUCKET_SIZE));
    buckets[index].count += 1;
  });
  return { mean, deviation, minimum, maximum, buckets, count: ratings.length };
}

export default function EloDistribution({ entries, currentUserId }) {
  const summary = summarizeRatings(entries);
  if (!summary) return null;
  const { buckets, mean, deviation, minimum, maximum, count } = summary;
  const width = 600;
  const baseline = 102;
  const plotHeight = 72;
  const cellWidth = width / buckets.length;
  const maxCount = Math.max(...buckets.map((bucket) => bucket.count), 1);
  const currentEntry = entries?.find((entry) => entry.user_id === currentUserId);
  const currentRating = currentEntry && !currentEntry.is_provisional ? currentEntry.elo_rating : null;
  const currentBucket = Number.isFinite(currentRating)
    ? Math.min(buckets.length - 1, Math.floor((currentRating - minimum) / BUCKET_SIZE))
    : -1;
  const normal = Array.from({ length: 61 }, (_, index) => {
    const rating = minimum + ((maximum - minimum || BUCKET_SIZE) * index / 60);
    const density = Math.exp(-0.5 * (((rating - mean) / deviation) ** 2));
    return `${index * width / 60},${baseline - (density * plotHeight)}`;
  }).join(' ');

  return (
    <div className="jk-card p-4 mb-4">
      <div className="flex items-baseline justify-between gap-3 mb-2">
        <p className="jk-label" style={{ fontSize: 10 }}>RATING DISTRIBUTION</p>
        <p className="jk-label" style={{ fontSize: 9 }}>{count} ranked players</p>
      </div>
      <svg className="jk-elo-distribution" viewBox={`0 0 ${width} 106`} role="img" aria-label={`ELO distribution from ${minimum} to ${maximum}; field center ${Math.round(mean)}`}>
        {buckets.map((bucket, index) => {
          const height = bucket.count ? Math.max(8, (bucket.count / maxCount) * 58) : 3;
          return (
            <rect
              key={bucket.lower}
              className={`jk-elo-distribution-bucket${index === currentBucket ? ' is-you' : ''}`}
              x={(index * cellWidth) + 3}
              y={baseline - height}
              width={Math.max(2, cellWidth - 6)}
              height={height}
              rx="3"
            />
          );
        })}
        <polyline className="jk-elo-distribution-curve" points={normal} />
        <line className="jk-elo-distribution-mean" x1={(mean - minimum) / (maximum - minimum || 1) * width} x2={(mean - minimum) / (maximum - minimum || 1) * width} y1="22" y2={baseline} />
      </svg>
      <div className="jk-elo-distribution-labels" aria-hidden="true">
        <span>{minimum}</span><span>field center {Math.round(mean)}</span><span>{maximum}</span>
      </div>
    </div>
  );
}
