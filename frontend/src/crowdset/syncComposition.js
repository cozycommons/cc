export default function syncComposition({ base, overlay, still, cuts, source }) {
  let frame;
  let decodedFrame;
  let pictureTime;
  let loaded;
  let failed = false;
  let disposed = false;
  let playPending = false;
  let seeking = false;
  let aligned = false;
  let hasPicture = false;
  let waitingSince;
  let lastSeek = -Infinity;
  let generation = 0;

  const activeCut = () => cuts.find((cut) => cut.start - 0.000001 <= base.currentTime && base.currentTime < cut.end - 0.000001);
  const hide = () => { overlay.style.visibility = 'hidden'; still.style.visibility = 'hidden'; };
  const cancelDecoded = () => {
    if (decodedFrame !== undefined) overlay.cancelVideoFrameCallback?.(decodedFrame);
    decodedFrame = undefined;
  };
  const fail = () => { failed = true; cancelDecoded(); hide(); overlay.pause(); };
  const hold = () => {
    if (overlay.style.visibility !== 'visible' || !overlay.videoWidth || !overlay.videoHeight) return;
    try {
      const scale = Math.min(1, 1280 / overlay.videoWidth);
      still.width = Math.round(overlay.videoWidth * scale);
      still.height = Math.round(overlay.videoHeight * scale);
      still.getContext('2d').drawImage(overlay, 0, 0, still.width, still.height);
      still.style.visibility = 'visible';
      overlay.style.visibility = 'hidden';
    } catch { /* Keep the video’s last frame if a browser cannot copy it. */ }
  };
  const reveal = (mediaTime) => {
    const active = activeCut();
    if (disposed || failed || seeking || overlay.seeking || base.seeking || !active || active.asset_id !== loaded) return;
    if (Math.abs(mediaTime - (base.currentTime - active.start)) > 0.35) return;
    aligned = true;
    waitingSince = undefined;
    overlay.style.visibility = 'visible';
    still.style.visibility = 'hidden';
  };
  const awaitPicture = () => {
    if (!overlay.requestVideoFrameCallback || decodedFrame !== undefined) return;
    const current = generation;
    decodedFrame = overlay.requestVideoFrameCallback((_, metadata) => {
      if (current !== generation || disposed) return;
      decodedFrame = undefined;
      pictureTime = metadata.mediaTime;
      reveal(pictureTime);
      if (activeCut() && !base.paused) awaitPicture();
    });
  };
  const ready = () => {
    if (overlay.seeking || overlay.readyState < 2) return;
    seeking = false;
    hasPicture = true;
    // Older embedded browsers lack compositor callbacks; media events gate their reveal.
    if (!overlay.requestVideoFrameCallback) reveal(overlay.currentTime);
    else awaitPicture();
  };
  const baseSeek = () => { hold(); aligned = false; waitingSince = undefined; lastSeek = -Infinity; };
  overlay.addEventListener('error', fail);
  overlay.addEventListener('loadeddata', ready);
  overlay.addEventListener('seeked', ready);
  base.addEventListener('seeking', baseSeek);

  function sync() {
    const active = activeCut();
    const next = active || cuts.find((cut) => cut.start > base.currentTime && cut.start - base.currentTime < 5);
    if (next?.asset_id !== loaded) {
      if (active) hold();
      else hide();
      cancelDecoded();
      generation += 1;
      loaded = next?.asset_id;
      failed = false;
      aligned = false;
      hasPicture = false;
      pictureTime = undefined;
      waitingSince = undefined;
      seeking = false;
      lastSeek = -Infinity;
      overlay.pause();
      overlay.style.visibility = 'hidden';
      if (next) overlay.src = source(loaded);
      else overlay.removeAttribute('src');
      overlay.load();
    }
    if (!active) { hide(); waitingSince = undefined; }
    else if (!aligned && waitingSince === undefined) waitingSince = performance.now();
    const target = active ? Math.max(0, base.currentTime - active.start) : 0;
    const drift = target - overlay.currentTime;
    const now = performance.now();
    if (next && !failed && !base.seeking && !seeking && !overlay.seeking && overlay.readyState >= 1
        && Math.abs(drift) > (aligned && !base.paused ? 0.75 : 0.12) && now - lastSeek > 1000) {
      hold();
      cancelDecoded();
      generation += 1;
      seeking = true;
      pictureTime = undefined;
      hasPicture = false;
      lastSeek = now;
      overlay.currentTime = target;
      awaitPicture();
    }
    if (!failed && ((seeking && now - lastSeek > 5000) || (waitingSince !== undefined && now - waitingSince > 5000))) fail();
    overlay.muted = true;
    overlay.playbackRate = base.playbackRate * (aligned && !base.paused ? 1 + Math.max(-0.05, Math.min(0.05, drift * 0.1)) : 1);
    if (active && !failed) {
      if (overlay.requestVideoFrameCallback && pictureTime !== undefined) reveal(pictureTime);
      else if (!overlay.requestVideoFrameCallback && hasPicture) reveal(overlay.currentTime);
      awaitPicture();
    }
    if (active && !failed && !base.paused && !base.seeking && base.readyState >= 3 && overlay.readyState >= 2) {
      if (overlay.paused && !playPending) {
        playPending = true;
        const current = generation;
        overlay.play().catch((error) => {
          if (!disposed && current === generation && error.name !== 'AbortError') fail();
        }).finally(() => { playPending = false; });
      }
    } else if (!overlay.paused) overlay.pause();
    frame = requestAnimationFrame(sync);
  }
  frame = requestAnimationFrame(sync);
  return () => {
    disposed = true;
    cancelAnimationFrame(frame);
    cancelDecoded();
    overlay.removeEventListener('error', fail);
    overlay.removeEventListener('loadeddata', ready);
    overlay.removeEventListener('seeked', ready);
    base.removeEventListener('seeking', baseSeek);
    overlay.pause();
    hide();
  };
}
