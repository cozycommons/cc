import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useCozyAuth } from './useCozyAuth';
import './oauth-consent.css';

function redirectBrowser(value) {
  window.location.assign(value);
}

function redirectUrl(value) {
  if (typeof value !== 'string' || !value) throw new Error('The application did not return a redirect address. Start again from your agent.');
  const url = new URL(value);
  if (url.protocol !== 'https:' && !(url.protocol === 'http:' && ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname))) {
    throw new Error('The application returned an unsupported redirect address.');
  }
  return url.href;
}

export default function OAuthConsent({ onRedirect = redirectBrowser }) {
  const { supabase, user, loading, signIn } = useCozyAuth();
  const [params] = useSearchParams();
  const authorizationId = params.get('authorization_id');
  const validRequest = authorizationId && /^[A-Za-z0-9_-]{1,128}$/.test(authorizationId);
  const [details, setDetails] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const requestIdentity = `${user?.id}:${authorizationId}`;
  const currentRequest = useRef(requestIdentity);
  currentRequest.current = requestIdentity;
  const deciding = useRef(false);
  const mounted = useRef(true);
  const userId = user?.id;

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  useEffect(() => {
    if (!userId || !validRequest) return;
    let active = true;
    setDetails(null);
    setError('');
    supabase.auth.oauth.getAuthorizationDetails(authorizationId).then(({ data, error: failure }) => {
      if (!active) return;
      if (failure) throw failure;
      if (data?.redirect_url) {
        onRedirect(redirectUrl(data.redirect_url));
        return;
      }
      if (data?.authorization_id !== authorizationId || data?.user?.id !== userId || !(data?.client?.id || data?.client?.client_id)) {
        throw new Error('This connection request is invalid. Start again from your agent.');
      }
      setDetails(data);
    }).catch((failure) => { if (active) setError(failure.message || 'Could not load this connection request.'); });
    return () => { active = false; };
  }, [supabase, authorizationId, validRequest, userId, attempt, onRedirect]);

  const decide = async (approve) => {
    if (deciding.current) return;
    deciding.current = true;
    setBusy(true); setError('');
    try {
      const method = approve ? 'approveAuthorization' : 'denyAuthorization';
      const { data, error: failure } = await supabase.auth.oauth[method](authorizationId, { skipBrowserRedirect: true });
      if (!mounted.current) return;
      if (failure) throw failure;
      if (currentRequest.current !== requestIdentity) throw new Error('Your connection request changed. Start again from your agent.');
      onRedirect(redirectUrl(data?.redirect_url));
    } catch (failure) { if (mounted.current) setError(failure.message || 'Could not complete this connection request.'); }
    finally { deciding.current = false; if (mounted.current) setBusy(false); }
  };

  const login = async () => {
    setBusy(true); setError('');
    try { await signIn(); }
    catch (failure) { setError(failure.message || 'Could not sign in. Please retry.'); }
    finally { setBusy(false); }
  };

  const ready = details?.user?.id === userId && details?.authorization_id === authorizationId;
  return <main className="cc-oauth-page"><section className="cc-oauth-card" aria-label="Application connection">
    <a className="cc-oauth-brand" href="/">COZY COMMONS</a>
    <h1>Connect an application</h1>
    {!validRequest ? <p role="alert">Missing or invalid connection request. Start the connection from your agent.</p>
      : loading ? <p role="status">Checking sign-in…</p>
        : !user ? <><p>Sign in to review this connection request.</p><button className="cc-oauth-button" disabled={busy} onClick={login}>Sign in</button></>
          : ready ? <>
            <p><strong>{details.client.name || details.client.client_name || details.client.id || details.client.client_id}</strong> is requesting access to your Cozy Commons account.</p>
            <p className="cc-oauth-account">{user.email}</p>
            {details.scope && <><h2>Requested scopes</h2><ul>{details.scope.split(/\s+/).filter(Boolean).map((scope) => <li key={scope}>{scope}</li>)}</ul></>}
            <div className="cc-oauth-actions"><button className="cc-oauth-button" disabled={busy} onClick={() => decide(true)}>{busy ? 'Continuing…' : 'Allow connection'}</button><button className="cc-oauth-button cc-oauth-secondary" disabled={busy} onClick={() => decide(false)}>Deny</button></div>
          </> : !error && <p role="status">Loading connection request…</p>}
    {error && <div role="alert"><p>{error}</p>{!ready && user && <button className="cc-oauth-button" disabled={busy} onClick={() => setAttempt((value) => value + 1)}>Retry</button>}</div>}
  </section></main>;
}
