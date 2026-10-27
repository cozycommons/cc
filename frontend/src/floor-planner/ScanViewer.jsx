import { useEffect, useRef, useState } from 'react';

export default function ScanViewer({ bytes }) {
  const container = useRef(null), renderer = useRef(null);
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState({ loading: true, error: '' });
  useEffect(() => {
    let active = true, mounted;
    const target = container.current;
    setState({ loading: true, error: '' });
    import('./scanRenderer').then(({ mountScan }) => mountScan(target, bytes, (error) => {
      if (active) { mounted?.dispose(); renderer.current = null; setState({ loading: false, error: error.message }); }
    })).then((view) => {
      mounted = view;
      if (!active) { view.dispose(); return; }
      renderer.current = view;
      setState({ loading: false, error: '' });
    }).catch((error) => { if (active) setState({ loading: false, error: error.message || 'Could not open this scan.' }); });
    return () => { active = false; mounted?.dispose(); renderer.current = null; };
  }, [bytes, attempt]);
  return <section className="fp-scan-viewer" aria-label="3D scan viewer">
    <div className="fp-scan-canvas" ref={container} tabIndex={0} aria-label="3D scan. Drag to orbit, right-drag to pan, scroll to zoom." />
    {state.loading && <p className="fp-scan-overlay" role="status">Loading 3D scan…</p>}
    {state.error && <div className="fp-scan-overlay" role="alert"><p>{state.error}</p><button type="button" onClick={() => setAttempt((value) => value + 1)}>Retry viewer</button></div>}
    {!state.loading && !state.error && <div className="fp-scan-viewer-controls"><span>Drag to orbit · right-drag to pan · scroll to zoom</span><button type="button" onClick={() => renderer.current?.fit()}>Fit scan</button></div>}
  </section>;
}
