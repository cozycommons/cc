import React, { useEffect, useRef, useState } from 'react';
import AdminPanel from './AdminPanel.jsx';
import { getLeague, saveLeague } from './admin.js';

const validSeason = value => /^[0-9]{4}$/.test(value) && Number(value) >= 2000 && Number(value) <= 2100;
const validId = value => /^[0-9]{1,12}$/.test(value);

// Mounted only while open; the header's admin icon owns open/closed.
export default function FantasyAdmin({ apiUrl, token, initialSeason, onSaved, onClose }) {
  const [season, setSeason] = useState(String(initialSeason || new Date().getFullYear() + (new Date().getMonth() >= 6 ? 1 : 0)));
  const [leagueId, setLeagueId] = useState('');
  const [state, setState] = useState({ loading: true });
  const generation = useRef(0);
  useEffect(() => {
    const request = ++generation.current;
    const controller = new AbortController();
    setLeagueId('');
    setState({ loading: true });
    if (!validSeason(season)) {
      setState({ error: 'Enter a season from 2000 to 2100.' });
      return;
    }
    getLeague(apiUrl, token, season, controller.signal).then(body => {
      if (request !== generation.current) return;
      setLeagueId(body.espn_league_id || '');
      setState({});
    }).catch(error => {
      if (request === generation.current && error.name !== 'AbortError') setState({ error: 'Could not load settings.' });
    });
    return () => { controller.abort(); };
  }, [apiUrl, token, season]);
  const save = async () => {
    if (!validSeason(season) || !validId(leagueId)) {
      setState({ error: 'Enter a season and a league ID of 1–12 digits.' });
      return;
    }
    const request = ++generation.current;
    setState({ saving: true });
    try {
      await saveLeague(apiUrl, token, season, leagueId);
      if (request !== generation.current) return;
      setState({ status: 'saved' });
      onSaved?.();
    } catch {
      if (request === generation.current) setState({ error: 'Could not save. Try again.' });
    }
  };
  const close = () => {
    generation.current++;
    onClose?.();
  };
  return (
    <AdminPanel season={season} onSeasonChange={value => { generation.current++; setSeason(value); }}
      leagueId={leagueId} onLeagueIdChange={value => { generation.current++; setLeagueId(value); setState({}); }}
      onSave={save} onClose={close} {...state}
      leagueUrl={validSeason(season) && validId(leagueId) ? `https://fantasy.espn.com/basketball/league?leagueId=${leagueId}&seasonId=${season}` : null} />
  );
}
