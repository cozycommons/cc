import React from 'react';
import { endpoint } from './api';

export default function CompositionPlayer({ set, playerRef, onTimeUpdate }) {
  const container = React.useRef(null);
  const insert = React.useRef(null);
  const [playing, setPlaying] = React.useState(false);
  const [muted, setMuted] = React.useState(false);
  const [position, setPosition] = React.useState(0);
  const [message, setMessage] = React.useState('');
  const segments = JSON.stringify(set.video_timeline.segments.filter((segment) => segment.asset_id));
  const baseUrl = endpoint(`/${set.id}/video?v=${set.mix_revision}`);

  React.useEffect(() => {
    const base = playerRef.current;
    const overlay = insert.current;
    const cuts = JSON.parse(segments);
    let frame;
    let loaded;
    let failed = false;
    let playPending = false;
    const fail = () => { failed = true; overlay.style.visibility = 'hidden'; };
    overlay.addEventListener('error', fail);
    function sync() {
      const time = base.currentTime;
      const active = cuts.find((cut) => cut.start <= time && time < cut.end);
      const next = active || cuts.find((cut) => cut.start > time && cut.start - time < 5);
      if (next?.asset_id !== loaded) {
        loaded = next?.asset_id;
        failed = false;
        overlay.pause();
        overlay.style.visibility = 'hidden';
        if (next) {
          overlay.src = endpoint(`/${set.id}/overlays/${loaded}?v=${set.mix_revision}`);
          overlay.load();
        } else {
          overlay.removeAttribute('src');
          overlay.load();
        }
      }
      const target = active ? time - active.start : 0;
      const drift = Math.abs(overlay.currentTime - target);
      if (next && !failed && overlay.readyState >= 1 && !overlay.seeking && drift > 0.12) {
        overlay.currentTime = target;
      }
      overlay.muted = true;
      overlay.playbackRate = base.playbackRate;
      const ready = active && !failed && !base.seeking && !overlay.seeking && overlay.readyState >= 2 && drift <= 0.15;
      overlay.style.visibility = ready ? 'visible' : 'hidden';
      if (active && !failed && !base.paused && !base.seeking && base.readyState >= 3 && overlay.readyState >= 2) {
        if (overlay.paused && !playPending) {
          playPending = true;
          const asset = loaded;
          overlay.play().catch((error) => {
            if (asset === loaded && error.name !== 'AbortError') fail();
          }).finally(() => { playPending = false; });
        }
      } else if (!overlay.paused) overlay.pause();
      frame = requestAnimationFrame(sync);
    }
    frame = requestAnimationFrame(sync);
    return () => {
      cancelAnimationFrame(frame);
      overlay.removeEventListener('error', fail);
      overlay.pause();
    };
  }, [segments, set.id, set.mix_revision, playerRef]);

  async function toggle() {
    const base = playerRef.current;
    if (!base.paused) { base.pause(); insert.current.pause(); return; }
    setMessage('');
    // A tap also unlocks the muted insert on browsers that require a gesture.
    if (insert.current.getAttribute('src')) insert.current.play().catch(() => {});
    try { await base.play(); } catch { setMessage('Playback could not start. Try again.'); }
  }

  return <div ref={container} className="cs-composition">
    <div className="cs-composition-picture">
      <video ref={playerRef} src={baseUrl} playsInline preload="metadata" disablePictureInPicture
        aria-label="Current cut" onTimeUpdate={(event) => { setPosition(event.currentTarget.currentTime); onTimeUpdate(event); }} onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)} onEnded={() => setPlaying(false)}
        onError={() => setMessage('The full set could not load. Reload the set to retry.')} />
      <video ref={insert} className="cs-composition-insert" muted playsInline preload="auto"
        disablePictureInPicture aria-label="Friend’s picture" />
    </div>
    <div className="cs-composition-controls">
      <button onClick={toggle}>{playing ? 'Pause' : 'Play'}</button>
      <input type="range" aria-label="Seek video" min="0" max={set.video_timeline.duration || 0} step="0.1"
        value={position} onChange={(event) => { const time = Number(event.target.value); playerRef.current.currentTime = time; setPosition(time); }} />
      <button onClick={() => { playerRef.current.muted = !muted; setMuted(!muted); }}>{muted ? 'Unmute' : 'Mute'}</button>
      {typeof document.documentElement.requestFullscreen === 'function' && <button onClick={() => {
        const operation = document.fullscreenElement ? document.exitFullscreen() : container.current.requestFullscreen();
        operation?.catch(() => setMessage('Fullscreen is unavailable. Continue watching inline.'));
      }}>Fullscreen</button>}
    </div>
    {message && <p role="status">{message}</p>}
  </div>;
}
