import React from 'react';
import { endpoint } from './api';

function sheetUrl(set, sheet) {
  return endpoint(`/${set.id}/previews/${sheet}?v=${set.mix_revision}`);
}

export function previewFrame(set, time) {
  const segment = set.video_timeline?.segments?.find((item) => item.start <= time && time < item.end);
  const source = set.scrub_previews?.[segment?.clip_id];
  if (!source) return null;
  const frame = Math.max(0, Math.min(source.count - 1, Math.floor((time - segment.offset - source.start) / source.interval)));
  const tileCount = source.columns * source.rows;
  const sheet = source.sheets[Math.floor(frame / tileCount)];
  if (!sheet) return null;
  return {
    src: sheetUrl(set, sheet),
    size: `${source.columns * 100}% ${source.rows * 100}%`,
    position: `${(frame % source.columns) / Math.max(1, source.columns - 1) * 100}% ${Math.floor(frame % tileCount / source.columns) / Math.max(1, source.rows - 1) * 100}%`,
  };
}

export function useScrubPreviews(set) {
  const urls = JSON.stringify([...new Set(Object.values(set.scrub_previews || {}).flatMap((source) => source.sheets.map((sheet) => sheetUrl(set, sheet))))]);
  const [loaded, setLoaded] = React.useState({ urls: null, images: new Map() });
  React.useEffect(() => {
    const pending = JSON.parse(urls);
    const images = [];
    const controller = new AbortController();
    let cancelled = false;
    async function preload() {
      while (!cancelled && pending.length) {
        const src = pending.shift();
        try {
          const response = await fetch(src, { credentials: 'same-origin', signal: controller.signal });
          if (!response.ok) continue;
          const blob = await response.blob();
          if (cancelled) return;
          const url = URL.createObjectURL(blob);
          const image = new Image();
          images.push({ image, url });
          image.src = url;
          await image.decode();
          if (!cancelled) setLoaded((previous) => ({ urls, images: new Map([...(previous.urls === urls ? previous.images : []), [src, url]]) }));
        } catch { /* Keep the timestamp usable if an optional preview fails. */ }
      }
    }
    for (let index = 0; index < 4; index += 1) preload();
    return () => {
      cancelled = true;
      controller.abort();
      images.forEach(({ image, url }) => { image.src = ''; URL.revokeObjectURL(url); });
    };
  }, [urls]);
  return loaded.urls === urls ? loaded.images : new Map();
}

export default function ScrubPreview({ set, time, left, label, loaded }) {
  const frame = previewFrame(set, time);
  return <div className="cs-scrub-preview" style={{ '--preview-left': left }} role="img" aria-label={`Video preview at ${label}`}>
    {frame && loaded?.has(frame.src) && <div className="cs-scrub-picture">
      <div className="cs-scrub-sprite" style={{ backgroundImage: `url("${loaded.get(frame.src)}")`, backgroundSize: frame.size, backgroundPosition: frame.position }} />
    </div>}
    <span className="cs-scrub-time">{label}</span>
  </div>;
}
