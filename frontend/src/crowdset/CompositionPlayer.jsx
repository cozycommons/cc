import React from 'react';
import { Play, Pause, Volume2, VolumeX, Maximize, Minimize, RectangleHorizontal, X, LoaderCircle } from 'lucide-react';
import { endpoint } from './api';

export function playbackTime(seconds) {
  const total = Math.floor(Math.max(0, seconds || 0));
  const minutes = Math.floor(total / 60);
  return `${minutes >= 60 ? `${Math.floor(minutes / 60)}:` : ''}${String(minutes % 60).padStart(minutes >= 60 ? 2 : 1, '0')}:${String(total % 60).padStart(2, '0')}`;
}

export default function CompositionPlayer({ set, playerRef, onTimeUpdate, theater = false, onTheaterChange }) {
  const container = React.useRef(null);
  const insert = React.useRef(null);
  const [playing, setPlaying] = React.useState(false);
  const [muted, setMuted] = React.useState(false);
  const [position, setPosition] = React.useState(0);
  const [message, setMessage] = React.useState('');
  const [volume, setVolume] = React.useState(1);
  const [duration, setDuration] = React.useState(set.video_timeline?.duration || 0);
  const [buffered, setBuffered] = React.useState(0);
  const [buffering, setBuffering] = React.useState(false);
  const [controls, setControls] = React.useState(true);
  const [fullscreen, setFullscreen] = React.useState(false);
  const [expanded, setExpanded] = React.useState(false);
  const hideTimer = React.useRef(null);
  const previousVolume = React.useRef(1);
  const wake = React.useCallback(() => {
    setControls(true);
    clearTimeout(hideTimer.current);
    hideTimer.current = setTimeout(() => setControls(false), 3000);
  }, []);
  React.useEffect(() => { wake(); return () => clearTimeout(hideTimer.current); }, [playing, wake]);
  React.useEffect(() => {
    const changed = () => setFullscreen(document.fullscreenElement === container.current);
    document.addEventListener('fullscreenchange', changed);
    return () => document.removeEventListener('fullscreenchange', changed);
  }, []);
  React.useEffect(() => {
    if (!expanded) return;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const escape = (event) => { if (event.key === 'Escape') setExpanded(false); };
    document.addEventListener('keydown', escape);
    return () => { document.body.style.overflow = overflow; document.removeEventListener('keydown', escape); };
  }, [expanded]);
  const segments = JSON.stringify((set.video_timeline?.segments || []).filter((segment) => segment.asset_id));
  const baseUrl = endpoint(`/${set.id}/video?v=${set.mix_revision}`);

  React.useEffect(() => {
    const base = playerRef.current;
    const overlay = insert.current;
    const cuts = JSON.parse(segments);
    if (!overlay || !cuts.length) return;
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
    if (!base.paused) { base.pause(); insert.current?.pause(); return; }
    setMessage('');
    // A tap also unlocks the muted insert on browsers that require a gesture.
    if (insert.current?.getAttribute('src')) insert.current.play().catch(() => {});
    try { await base.play(); } catch { setMessage('Playback could not start. Try again.'); }
  }

  function seek(time) {
    const value = Math.max(0, Math.min(duration, time));
    playerRef.current.currentTime = value;
    setPosition(value);
  }
  function changeVolume(value) {
    const video = playerRef.current;
    video.volume = value;
    video.muted = value === 0;
    if (value > 0) previousVolume.current = value;
    setVolume(video.volume);
    setMuted(video.muted);
  }
  function toggleMute() {
    const video = playerRef.current;
    if (video.muted || video.volume === 0) {
      video.volume = previousVolume.current;
      video.muted = false;
    } else video.muted = true;
    setMuted(video.muted);
    setVolume(video.volume);
  }
  async function toggleFullscreen() {
    if (expanded) { setExpanded(false); return; }
    try {
      if (document.fullscreenElement === container.current) await document.exitFullscreen();
      else if (container.current.requestFullscreen) await container.current.requestFullscreen();
      else setExpanded(true);
    } catch { setExpanded(true); }
    wake();
  }
  function keyboard(event) {
    if (event.altKey || event.ctrlKey || event.metaKey || event.target.tagName === 'INPUT') return;
    const button = event.target.tagName === 'BUTTON';
    const key = event.key.toLowerCase();
    if ((key === ' ' && !button) || key === 'k') toggle();
    else if (key === 'm') toggleMute();
    else if (key === 'f') toggleFullscreen();
    else if (key === 't' && onTheaterChange) onTheaterChange(!theater);
    else if (key === 'arrowright' || key === 'l') seek(playerRef.current.currentTime + (key === 'l' ? 10 : 5));
    else if (key === 'arrowleft' || key === 'j') seek(playerRef.current.currentTime - (key === 'j' ? 10 : 5));
    else if (key === 'arrowup') changeVolume(Math.min(1, playerRef.current.volume + 0.05));
    else if (key === 'arrowdown') changeVolume(Math.max(0, playerRef.current.volume - 0.05));
    else return;
    event.preventDefault();
    wake();
  }
  const silent = muted || volume === 0;
  const full = fullscreen || expanded;
  const shown = controls || !playing || buffering || message;
  return <div ref={container} className={`cs-composition ${shown ? 'cs-controls-visible' : ''} ${expanded ? 'cs-player-expanded' : ''}`}
    role="region" aria-label="Video player" tabIndex={0} onKeyDown={keyboard} onPointerMove={wake} onFocusCapture={wake}>
    <div className="cs-composition-picture">
      <video ref={playerRef} src={baseUrl} playsInline preload="metadata" disablePictureInPicture
        aria-label="Current cut" onTimeUpdate={(event) => { setPosition(event.currentTarget.currentTime); onTimeUpdate(event); }}
        onLoadedMetadata={(event) => { if (Number.isFinite(event.currentTarget.duration)) setDuration(event.currentTarget.duration); }}
        onPlay={() => setPlaying(true)} onPause={() => { setPlaying(false); setBuffering(false); }} onEnded={() => setPlaying(false)}
        onWaiting={() => setBuffering(true)} onPlaying={() => setBuffering(false)} onCanPlay={() => setBuffering(false)}
        onSeeked={() => setBuffering(false)}
        onVolumeChange={(event) => { setMuted(event.currentTarget.muted); setVolume(event.currentTarget.volume); }}
        onProgress={(event) => { const ranges = event.currentTarget.buffered; if (ranges.length) setBuffered(ranges.end(ranges.length - 1)); }}
        onError={() => { setBuffering(false); setMessage('The video could not load. Reload the set to retry.'); }} />
      {segments !== '[]' && <video ref={insert} className="cs-composition-insert" muted playsInline preload="auto"
        disablePictureInPicture aria-label="Friend’s picture" />}
      <button className="cs-player-screen" aria-label={playing ? 'Pause video' : 'Play video'} tabIndex={-1}
        onClick={toggle} onDoubleClick={toggleFullscreen}>
        {!playing && !buffering && <span className="cs-player-center"><Play size={30} fill="currentColor" aria-hidden="true" /></span>}
      </button>
      {buffering && <span className="cs-player-loading" role="status" aria-label="Buffering video"><LoaderCircle size={32} aria-hidden="true" /></span>}
    </div>
    <div className="cs-player-controls">
      <div className="cs-player-progress" style={{ '--played': `${duration ? position / duration * 100 : 0}%`, '--buffered': `${duration ? Math.min(buffered / duration * 100, 100) : 0}%` }}>
        <input type="range" aria-label="Seek video" aria-valuetext={`${playbackTime(position)} of ${playbackTime(duration)}`} min="0" max={duration} step="0.1"
          value={Math.min(position, duration)} onChange={(event) => seek(Number(event.target.value))} />
      </div>
      <div className="cs-player-buttons">
        <button aria-label={playing ? 'Pause' : 'Play'} title={playing ? 'Pause (k)' : 'Play (k)'} onClick={toggle}>{playing ? <Pause fill="currentColor" /> : <Play fill="currentColor" />}</button>
        <div className="cs-player-volume">
          <button aria-label={silent ? 'Unmute' : 'Mute'} title={silent ? 'Unmute (m)' : 'Mute (m)'} onClick={toggleMute}>{silent ? <VolumeX /> : <Volume2 />}</button>
          <input type="range" aria-label="Volume" min="0" max="1" step="0.05" value={silent ? 0 : volume} onChange={(event) => changeVolume(Number(event.target.value))} />
        </div>
        <span className="cs-player-time">{playbackTime(position)} <span>/ {playbackTime(duration)}</span></span>
        <span className="cs-player-spacer" />
        {onTheaterChange && !full && <button className="cs-theater-toggle" aria-label={theater ? 'Exit theater mode' : 'Theater mode'} aria-pressed={theater} title="Theater mode (t)" onClick={() => onTheaterChange(!theater)}><RectangleHorizontal /></button>}
        <button aria-label={full ? 'Exit fullscreen' : 'Fullscreen'} title={full ? 'Exit fullscreen (f)' : 'Fullscreen (f)'} onClick={toggleFullscreen}>{full ? <Minimize /> : <Maximize />}</button>
      </div>
    </div>
    {message && <div className="cs-player-message" role="alert">{message}<button aria-label="Dismiss playback message" onClick={() => setMessage('')}><X size={16} /></button></div>}
  </div>;
}
