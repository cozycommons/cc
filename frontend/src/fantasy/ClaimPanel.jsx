import React, { useEffect, useState } from 'react';
import { claimTeam, releaseTeam, signIn, signedInToken, suggestions } from './claims.js';
import { TeamLogo } from './parts.jsx';


const ERRORS = {
  profile_required: 'Make a Dice profile first; its name and photo show here.',
  team_claimed: 'Someone already linked that team.',
  name_mismatch: 'That team’s manager name doesn’t match your profile. Ask an admin to link it.',
};

// Link your Dice profile to your ESPN team: suggest a match, show it only after you confirm.
export default function ClaimPanel({ apiUrl, data, onChange }) {
  const [state, setState] = useState({ status: apiUrl ? 'checking' : 'off' });
  const [choice, setChoice] = useState('');

  const refresh = async () => {
    const token = await signedInToken();
    if (!token) return setState({ status: 'signed-out' });
    try {
      setState({ status: 'ready', ...(await suggestions(apiUrl, token)) });
    } catch (error) {
      setState({ status: error.status === 401 ? 'signed-out' : 'error' });
    }
  };
  useEffect(() => { if (apiUrl) refresh(); }, [apiUrl]); // eslint-disable-line react-hooks/exhaustive-deps

  if (state.status === 'off') return null;
  if (state.status === 'checking') {
    return (
      <section className="fx-claim" aria-label="Your team" aria-busy="true">
        <h3>Your team</h3>
        <p className="fx-small">Checking…</p>
      </section>
    );
  }
  if (state.status === 'error') {
    return (
      <section className="fx-claim" aria-label="Your team">
        <h3>Your team</h3>
        <p className="fx-small">Team linking isn’t available right now. <button type="button" onClick={refresh}>Retry</button></p>
      </section>
    );
  }
  // Ask for the token at click time: Supabase refreshes sessions in the background.
  const run = async action => {
    try {
      setState(current => ({ ...current, busy: true, message: null }));
      const token = await signedInToken();
      if (!token) return setState({ status: 'signed-out' });
      await action(token);
      await refresh();
      onChange();
    } catch (error) {
      if (error.status === 401) return refresh();
      setState(current => ({ ...current, busy: false, message: ERRORS[error.detail] || 'That didn’t work. Try again.' }));
    }
  };

  if (state.status === 'signed-out') {
    return (
      <p className="fx-small fx-linked" aria-label="Your team"><button type="button" className="fx-text-button" onClick={() => signIn()}>Sign in</button> to link your team</p>
    );
  }

  const season = state.season ?? data.year;
  const team = id => data.teams.get(id);
  // The server's team list is the source of truth; the snapshot only adds logos.
  const serverTeam = id => (state.teams || []).find(t => t.team_id === id);
  const mine = state.mine
    ? { ...team(state.mine.team_id), id: state.mine.team_id, name: serverTeam(state.mine.team_id)?.name ?? team(state.mine.team_id)?.name }
    : null;
  const open = (state.teams || []).filter(t => !t.claimed && t.can_claim);
  const best = open.find(t => t.score >= 0.6);
  if (mine) {
    return (
      <p className="fx-small fx-linked">{mine.name} · <button type="button" className="fx-text-button" disabled={state.busy}
        onClick={() => run(token => releaseTeam(apiUrl, token, season, mine.id))}>Unlink</button></p>
    );
  }
  return (
    <section className="fx-claim" aria-label="Your team">
      <h3>Your team</h3>
      {!state.has_profile && <p className="fx-small">{ERRORS.profile_required} <a href="/dice">Open Dice</a></p>}
      {!mine && state.has_profile && (
        <>
          {best && (
            <div className="fx-claim-row">
              <TeamLogo team={team(best.team_id) || { name: best.name }} side={0} size={32} />
              <span>Is this you? <b>{best.name}</b>{best.manager && <small> · {best.manager}</small>}</span>
              <button type="button" className="fx-claim-primary" disabled={state.busy}
                onClick={() => run(token => claimTeam(apiUrl, token, season, best.team_id))}>That’s me</button>
            </div>
          )}
          {open.length ? (
          <div className="fx-claim-row">
            <label htmlFor="fx-claim-pick">{best ? 'Different team' : 'Pick your team'}</label>
            <select id="fx-claim-pick" value={choice} onChange={event => setChoice(event.target.value)}>
              <option value="">Choose…</option>
              {open.map(t => <option key={t.team_id} value={t.team_id}>{t.name}{t.manager ? ` (${t.manager})` : ''}</option>)}
            </select>
            <button type="button" disabled={!choice || state.busy} onClick={() => run(token => claimTeam(apiUrl, token, season, Number(choice)))}>Link</button>
          </div>
          ) : <p className="fx-small">No open team matches your profile name. Ask an admin to link yours.</p>}
        </>
      )}
      {state.message && <p className="fx-small" role="alert">{state.message}</p>}
    </section>
  );
}
