import React from 'react';
import ScrubPreview from './ScrubPreview';

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

export default function MixTimeline({ timeline, clips, currentTime, onSeek, video = false, set, previews }) {
  const [hoverTime, setHoverTime] = React.useState(null);
  const patternId = React.useId().replaceAll(':', '');
  const duration = timeline.duration;
  if (!duration) return null;
  const position = Math.min(duration, Math.max(0, currentTime));
  const inspected = hoverTime ?? position;
  const active = timeline.segments.filter((segment) => segment.start - 0.000001 <= inspected && inspected < segment.end - 0.000001);
  const name = (id) => clips.find((clip) => clip.id === id)?.name || 'Removed recording';
  const used = [...new Set(timeline.segments.map((segment) => segment.clip_id))];
  const describe = (segment) => `${timestamp(segment.start)}–${timestamp(segment.end)}`;
  const detail = active.length ? `${active.map((segment) => name(segment.clip_id)).join(' + ')}${active.length > 1 ? ' · Crossfade' : ''}` : inspected >= duration ? 'End of mix' : video ? 'No aligned video' : 'Silence';
  return <div className="cs-timeline">
    <div className="cs-timeline-heading"><span>{used.length} {used.length === 1 ? 'source' : 'sources'}</span></div>
    <div className="cs-timeline-strip">
      {video && set && hoverTime !== null && <ScrubPreview set={set} time={hoverTime} left={`${hoverTime / duration * 100}%`} label={timestamp(hoverTime)} loaded={previews} />}
      <svg viewBox="0 0 1000 32" preserveAspectRatio="none" aria-hidden="true">
        <defs><pattern id={patternId} width="6" height="6" patternUnits="userSpaceOnUse"><path d="M0 6L6 0" stroke="#fff" strokeWidth="1.5" /></pattern></defs>
        <rect width="1000" height="32" fill="#d7d1c5" />
        {timeline.segments.map((segment, index) => <rect key={index} x={segment.start / duration * 1000} y="0" width={(segment.end - segment.start) / duration * 1000} height="32" fill={recordingColor(segment.clip_id, clips)}><title>{name(segment.clip_id)} · {describe(segment)}</title></rect>)}
        {timeline.segments.filter((segment) => segment.fade_in > 0).map((segment, index) => <rect key={index} x={segment.start / duration * 1000} y="0" width={segment.fade_in / duration * 1000} height="32" fill={`url(#${patternId})`} />)}
        <line x1={position / duration * 1000} x2={position / duration * 1000} y1="0" y2="32" stroke="#fff" strokeWidth="3" />
      </svg>
      <input type="range" min="0" max={duration} step="0.1" value={position} aria-label="Seek mix" aria-valuetext={`${timestamp(position)} of ${timestamp(duration)}`}
        onChange={(event) => { const value = Number(event.target.value); onSeek(value); setHoverTime(value); }}
        onPointerMove={(event) => { if (event.pointerType === 'touch' && !event.buttons) return; const bounds = event.currentTarget.getBoundingClientRect(); setHoverTime(Math.max(0, Math.min(duration, (event.clientX - bounds.left) / bounds.width * duration))); }}
        onFocus={() => setHoverTime(position)} onBlur={() => setHoverTime(null)}
        onPointerLeave={() => setHoverTime(null)} onPointerUp={(event) => { if (event.pointerType === 'touch') setHoverTime(null); }} onPointerCancel={() => setHoverTime(null)} />
    </div>
    <div className="cs-timeline-times"><span>{timestamp(position)}</span><span>{timestamp(duration)}</span></div>
    <p className="cs-timeline-detail">{detail}</p>
    <div className="cs-timeline-legend">{used.map((id) => {
      const start = Math.min(...timeline.segments.filter((segment) => segment.clip_id === id).map((segment) => segment.start));
      return <button type="button" key={id} title={`Jump to ${timestamp(start)} · ${name(id)}`} onClick={() => { setHoverTime(null); onSeek(start); }}><span style={{ background: recordingColor(id, clips) }} />{name(id)}</button>;
    })}
    </div>
  </div>;
}
