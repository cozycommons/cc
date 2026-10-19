import React from 'react';

const colors = ['#356b85', '#9c5838', '#587444', '#815c91', '#a06b19', '#a34f70', '#387b72', '#5e63a0', '#71752c'];
export function recordingColor(id, clips = []) {
  const index = clips.findIndex((clip) => clip.id === id);
  if (index >= 0) return colors[index % colors.length];
  let hash = 0;
  for (const character of id) hash = ((hash * 31) + character.charCodeAt(0)) >>> 0;
  return colors[hash % colors.length];
}
function timestamp(seconds) {
  return `${Math.floor(seconds / 60)}:${Math.floor(seconds % 60).toString().padStart(2, '0')}`;
}

export default function MixTimeline({ timeline, clips, currentTime, onSeek, video = false }) {
  const [hoverTime, setHoverTime] = React.useState(null);
  const patternId = React.useId().replaceAll(':', '');
  const duration = timeline.duration;
  if (!duration) return null;
  const position = Math.min(duration, Math.max(0, currentTime));
  const inspected = hoverTime ?? position;
  const active = timeline.segments.filter((segment) => segment.start <= inspected && inspected < segment.end);
  const name = (id) => clips.find((clip) => clip.id === id)?.name || 'Removed recording';
  const used = [...new Set(timeline.segments.map((segment) => segment.clip_id))];
  const describe = (segment) => `${timestamp(segment.start)}–${timestamp(segment.end)}`;
  const detail = active.length ? `${active.map((segment) => name(segment.clip_id)).join(' + ')}${active.length > 1 ? ' · Crossfade' : ''}` : inspected >= duration ? 'End of mix' : video ? 'No aligned video' : 'Silence';
  return <div className="cs-timeline">
    <div className="cs-timeline-strip">
      <svg viewBox="0 0 1000 32" preserveAspectRatio="none" aria-hidden="true">
        <defs><pattern id={patternId} width="6" height="6" patternUnits="userSpaceOnUse"><path d="M0 6L6 0" stroke="#fff" strokeWidth="1.5" /></pattern></defs>
        <rect width="1000" height="32" fill="#d7d1c5" />
        {timeline.segments.map((segment, index) => <rect key={index} x={segment.start / duration * 1000} y="0" width={(segment.end - segment.start) / duration * 1000} height="32" fill={recordingColor(segment.clip_id, clips)}><title>{name(segment.clip_id)} · {describe(segment)}</title></rect>)}
        {timeline.segments.filter((segment) => segment.fade_in > 0).map((segment, index) => <rect key={index} x={segment.start / duration * 1000} y="0" width={segment.fade_in / duration * 1000} height="32" fill={`url(#${patternId})`} />)}
        <line x1={position / duration * 1000} x2={position / duration * 1000} y1="0" y2="32" stroke="#fff" strokeWidth="3" />
      </svg>
      <input type="range" min="0" max={duration} step="0.1" value={position} aria-label="Seek mix" aria-valuetext={`${timestamp(position)} of ${timestamp(duration)}`}
        title={`${timestamp(inspected)} · ${detail}`} onChange={(event) => onSeek(Number(event.target.value))}
        onPointerMove={(event) => { const bounds = event.currentTarget.getBoundingClientRect(); setHoverTime(Math.max(0, Math.min(duration, (event.clientX - bounds.left) / bounds.width * duration))); }}
        onPointerLeave={() => setHoverTime(null)} />
    </div>
    <div className="cs-timeline-times"><span>{timestamp(position)}</span><span>{timestamp(duration)}</span></div>
    <p className="cs-timeline-detail">{detail}</p>
    <div className="cs-timeline-legend">{used.map((id) => <a key={id} href={`#recording-${id}`} title={timeline.segments.filter((segment) => segment.clip_id === id).map(describe).join(', ')}><span style={{ background: recordingColor(id, clips) }} />{name(id)}</a>)}
    </div>
  </div>;
}
