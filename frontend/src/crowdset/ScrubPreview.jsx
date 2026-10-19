import React from 'react';
import { endpoint } from './api';

export function previewFrame(set, time) {
  const cut = set.video_timeline?.segments?.find((segment) => segment.asset_id && segment.start <= time && time < segment.end);
  return {
    src: endpoint(`/${set.id}/${cut ? `overlays/${cut.asset_id}` : 'video'}?v=${set.mix_revision}`),
    localTime: cut ? time - cut.start : time,
  };
}

export default function ScrubPreview({ set, time, left, label }) {
  const video = React.useRef(null);
  const [request, setRequest] = React.useState(null);
  const [ready, setReady] = React.useState(null);
  const [failed, setFailed] = React.useState(null);
  const { src, localTime } = previewFrame(set, time);
  React.useEffect(() => {
    const timer = setTimeout(() => setRequest({ src, localTime, time }), 180);
    return () => clearTimeout(timer);
  }, [src, localTime, time]);

  function seek() {
    const media = video.current;
    if (!request || !media || media.readyState < 1) return;
    const target = Math.min(request.localTime, Math.max(0, media.duration - 0.05));
    if (Number.isFinite(target)) media.currentTime = target;
  }
  function reveal() {
    const media = video.current;
    if (request && media && !media.seeking && media.readyState >= 2
        && Math.abs(media.currentTime - request.localTime) < 0.15) setReady(request);
  }
  React.useEffect(seek, [request]);
  React.useEffect(() => {
    const media = video.current;
    return () => {
      if (!media) return;
      media.pause();
      media.removeAttribute('src');
      media.load();
    };
  }, [request?.src]);
  const current = request?.time === time;
  return <div className="cs-scrub-preview" style={{ '--preview-left': left }} role="img" aria-label={`Video preview at ${label}`}>
    <div className="cs-scrub-picture">
      {request && <video key={request.src} ref={video} src={request.src} muted playsInline preload="metadata" aria-hidden="true"
        style={{ visibility: current && ready === request ? 'visible' : 'hidden' }}
        onLoadedMetadata={seek} onLoadedData={reveal} onSeeked={reveal} onError={() => setFailed(request.src)} />}
      {(!current || ready !== request) && <span>{current && failed === request?.src ? 'Preview unavailable' : 'Loading preview…'}</span>}
    </div>
    <span className="cs-scrub-time">{label}</span>
  </div>;
}
