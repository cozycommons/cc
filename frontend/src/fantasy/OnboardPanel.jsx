import React, { useRef, useState } from 'react';
import { onboardWithLogin } from './onboard.js';

const ERRORS = {
  invalid_credentials: 'ESPN didn’t accept that email and password. Check them and try again.',
  account_not_found: 'No ESPN account uses that email address.',
  challenge_required: 'ESPN asked for extra verification (like a CAPTCHA or a code) that this form can’t complete. Sign in at espn.com in your browser first, then use the cookie sign-up from the guide instead.',
  no_league_found: 'You’re signed in, but we couldn’t find a fantasy basketball league for this season on that account.',
  email_and_password_required: 'Enter your ESPN email and password.',
  league_discovery_failed: 'You’re signed in, but ESPN didn’t answer when we looked up your leagues. Try again in a minute.',
  disney_unavailable: 'ESPN’s sign-in isn’t answering right now. Try again in a minute.',
};

// Connect an ESPN account with its login, so daily lineup setting can run.
// The password is sent once to the backend and discarded — never stored.
export default function OnboardPanel({ apiUrl }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [label, setLabel] = useState('');
  const [automation, setAutomation] = useState(true);
  const [phase, setPhase] = useState('form'); // form | pick | done
  const [leagues, setLeagues] = useState([]);
  const [pick, setPick] = useState('');
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(null);
  const [copied, setCopied] = useState(false);
  const tokenRef = useRef(null);

  if (!apiUrl) return null;

  const submit = async leagueId => {
    setBusy(true);
    setMessage(null);
    try {
      const body = await onboardWithLogin(apiUrl, {
        email,
        password,
        label: label.trim(),
        enable_automation: automation,
        ...(leagueId ? { league_id: leagueId } : {}),
      });
      if (body.status === 'league_selection_required') {
        setLeagues(body.leagues || []);
        setPick('');
        setPhase('pick');
      } else {
        setResult(body);
        setPassword('');
        setPhase('done');
      }
    } catch (error) {
      setMessage(error.status === 429
        ? 'Too many sign-in attempts from here — wait a few minutes and try again.'
        : ERRORS[error.detail] || 'Something went wrong connecting your account. Try again.');
    } finally {
      setBusy(false);
    }
  };

  const copyToken = async () => {
    try {
      await navigator.clipboard.writeText(result.token);
      setCopied(true);
    } catch {
      tokenRef.current?.select();
    }
  };

  return (
    <section className="fx-onboard" aria-label="Automatic lineups">
      <h3>Automatic lineups</h3>
      {phase === 'done' ? (
        <>
          <p>
            You’re connected: <b>{result.league_name || 'your league'}</b>
            {result.team_name && <> — your team is <b>{result.team_name}</b></>}.{' '}
            {result.lineup_automation_enabled
              ? 'Daily lineup setting is on.'
              : 'Daily lineup setting is off — you can turn it on later with your token.'}
          </p>
          <label htmlFor="fx-onboard-token">Your personal token — this is the only time it’s shown, so save it now</label>
          <div className="fx-token-row">
            <input id="fx-onboard-token" ref={tokenRef} readOnly value={result.token} />
            <button type="button" onClick={copyToken}>{copied ? 'Copied' : 'Copy'}</button>
          </div>
        </>
      ) : phase === 'pick' ? (
        <>
          <p className="fx-small">You’re in more than one basketball league this season. Which one should we connect?</p>
          <div className="fx-onboard-row">
            <label htmlFor="fx-onboard-pick">League</label>
            <select id="fx-onboard-pick" value={pick} onChange={event => setPick(event.target.value)}>
              <option value="">Choose…</option>
              {leagues.map(entry => (
                <option key={entry.league_id} value={entry.league_id}>
                  {entry.name || `League ${entry.league_id}`}{entry.team_name ? ` — your team: ${entry.team_name}` : ''}
                </option>
              ))}
            </select>
            <button type="button" className="fx-claim-primary" disabled={!pick || busy}
              onClick={() => submit(Number(pick))}>
              {busy ? 'Connecting…' : 'Connect this league'}
            </button>
          </div>
        </>
      ) : (
        <>
          <p className="fx-small">
            Connect your ESPN account and Cozy Commons will set your starting lineup every day.
            We never store your ESPN password — it’s used once to connect and then discarded.
          </p>
          <form onSubmit={event => { event.preventDefault(); submit(); }}>
            <label htmlFor="fx-onboard-email">ESPN email</label>
            <input id="fx-onboard-email" type="email" autoComplete="username" required
              value={email} onChange={event => setEmail(event.target.value)} />
            <label htmlFor="fx-onboard-password">ESPN password</label>
            <input id="fx-onboard-password" type="password" autoComplete="current-password" required
              value={password} onChange={event => setPassword(event.target.value)} />
            <label htmlFor="fx-onboard-label">Your name (optional)</label>
            <input id="fx-onboard-label" type="text" autoComplete="nickname"
              value={label} onChange={event => setLabel(event.target.value)} />
            <label className="fx-check" htmlFor="fx-onboard-automation">
              <input id="fx-onboard-automation" type="checkbox"
                checked={automation} onChange={event => setAutomation(event.target.checked)} />
              Set my lineup automatically every day
            </label>
            <button type="submit" className="fx-claim-primary" disabled={busy}>
              {busy ? 'Connecting…' : 'Connect ESPN'}
            </button>
          </form>
          <p className="fx-small">
            What can this do? Lineup moves only — starters, bench, and IR.
            It cannot add, drop, or trade players; those actions don’t exist here.
          </p>
        </>
      )}
      {message && <p className="fx-small" role="alert">{message}</p>}
    </section>
  );
}
