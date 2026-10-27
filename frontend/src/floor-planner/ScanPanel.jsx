import { useEffect, useRef, useState } from 'react';
import ScanViewer from './ScanViewer';
import { MAX_SCAN_BYTES, scanRequest } from './scanApi';

export default function ScanPanel({ supabase, userId, planId }) {
  const [scan, setScan] = useState(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [bytes, setBytes] = useState(null);
  const [retry, setRetry] = useState(0);
  const input = useRef(null);

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    const load = () => scanRequest(supabase, userId, planId, { signal: controller.signal })
      .then((result) => { if (active) { setScan(result.scan); setLoading(false); } })
      .catch((failure) => {
        if (!active) return;
        if ([401, 403, 404].includes(failure.status)) { setScan(null); setBytes(null); }
        setError(failure.message); setLoading(false);
      });
    load();
    const timer = window.setInterval(load, 6000);
    return () => { active = false; controller.abort(); window.clearInterval(timer); };
  }, [supabase, userId, planId, retry]);

  useEffect(() => {
    setBytes(null);
    if (!scan) return;
    let active = true;
    const controller = new AbortController();
    setError('');
    scanRequest(supabase, userId, planId, { content: true, signal: controller.signal })
      .then((result) => { if (active) setBytes(result); })
      .catch((failure) => { if (active) setError(failure.message); });
    return () => { active = false; controller.abort(); };
  }, [supabase, userId, planId, scan?.id, retry]); // eslint-disable-line react-hooks/exhaustive-deps

  const upload = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.usdz')) { setError('Choose a USDZ file.'); return; }
    if (file.size > MAX_SCAN_BYTES) { setError('USDZ scans must be at most 50 MiB.'); return; }
    setBusy(true); setError('');
    try {
      const result = await scanRequest(supabase, userId, planId, { method: 'PUT', file, scanId: scan?.id });
      setScan(result.scan);
    } catch (failure) { setError(failure.message); }
    finally { setBusy(false); }
  };
  const remove = async () => {
    if (!window.confirm('Remove this scan from the plan?')) return;
    setBusy(true); setError('');
    try {
      await scanRequest(supabase, userId, planId, { method: 'DELETE', scanId: scan.id });
      setScan(null); setBytes(null);
    } catch (failure) { setError(failure.message); }
    finally { setBusy(false); }
  };
  return <section className="fp-scan-panel" aria-label="Attached scan">
    <div className="fp-scan-toolbar"><div><strong>{scan?.filename || '3D scan'}</strong><p>Shared with plan collaborators · excluded from the public gallery</p></div><div className="fp-scan-actions">
      <input ref={input} hidden type="file" accept=".usdz,model/vnd.usdz+zip" aria-label="Choose USDZ scan" onChange={upload} />
      <button type="button" disabled={busy || loading} onClick={() => input.current?.click()}>{busy ? 'Saving…' : scan ? 'Replace scan' : 'Upload USDZ'}</button>
      {scan && <button type="button" disabled={busy} onClick={remove}>Remove scan</button>}
    </div></div>
    {error && <div className="fp-scan-error" role="alert"><span>{error}</span><button type="button" disabled={busy} onClick={() => { setError(''); setRetry((value) => value + 1); }}>Retry</button></div>}
    {loading && <p role="status">Loading scan…</p>}
    {!loading && !scan && <div className="fp-scan-empty"><p>Upload an apartment scan to view it in 3D.</p><p>USDZ · up to 50 MiB</p></div>}
    {scan && !bytes && !error && <p role="status">Loading scan…</p>}
    {bytes && <ScanViewer bytes={bytes} />}
  </section>;
}
