import React, { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { favorite } from './paths.js';
import { COLORS, OddsTrend, ScorePath, TeamLogo, longDay, pct, round, weekday } from './parts.jsx';

const observed = day => day.state !== 'projected' && Array.isArray(day.actual) && day.actual.some(Number.isFinite);

function DayBars({ matchup, selected, onSelect }) {
  const value = day => (observed(day) ? day.actual : day.expected);
  const top = Math.max(1, ...matchup.days.flatMap(day => (value(day) || []).filter(Number.isFinite))) * 1.15;
  return (
    <div className="fx-bars" role="group" aria-label="Daily points; solid bars are actual, striped bars are projected">
      {matchup.days.map(day => {
        const values = value(day) || [null, null], projected = !observed(day);
        return (
          <button type="button" key={day.date} className="fx-bars-day" aria-pressed={selected === day.date}
            disabled={projected} onClick={() => onSelect(day.date)}
            aria-label={`${longDay(day.date)}: ${values.map(round).join(' to ')}${projected ? ' projected' : ''}`}>
            <span className="fx-bars-pair">
              {values.map((v, side) => (
                <span className="fx-bars-slot" key={side}>
                  {Number.isFinite(v) && <b>{round(v)}</b>}
                  <i className={projected ? 'fx-hatch' : undefined}
                    style={{ height: `${Number.isFinite(v) ? Math.max(0, v) / top * 100 : 0}%`, '--fx-side': COLORS[side] }} />
                </span>
              ))}
            </span>
            <small>{weekday(day.date)}{projected ? ' · proj.' : day.state === 'live' ? ' · live' : ''}</small>
          </button>
        );
      })}
    </div>
  );
}

function Players({ matchup, date }) {
  const day = matchup.days.find(d => d.date === date);
  if (!day?.players) return <p className="fx-small">Player details weren't published for this day.</p>;
  return (
    <div className="fx-players">
      {[matchup.home, matchup.away].map((team, side) => {
        const rows = [...day.players[side]].sort((a, b) => (b.points ?? -Infinity) - (a.points ?? -Infinity));
        return (
          <div key={side} className="fx-players-team">
            <h4><TeamLogo team={team} side={side} size={22} />{team.name}<span>{round(day.actual?.[side])}</span></h4>
            {rows.length ? <ol>{rows.map(player => (
              <li key={player.id}>
                <img src={`https://a.espncdn.com/i/headshots/nba/players/full/${player.id}.png`} alt="" loading="lazy"
                  referrerPolicy="no-referrer" onError={event => { event.currentTarget.style.visibility = 'hidden'; }} />
                <span>{player.name}</span>
                <b style={{ color: player.points < 0 ? '#a1442b' : undefined }}>{round(player.points)}</b>
              </li>
            ))}</ol> : <p className="fx-small">No games.</p>}
          </div>
        );
      })}
    </div>
  );
}

export default function MatchupPage({ data }) {
  const { key } = useParams();
  const matchup = data.matchups.find(m => m.key === key);
  const lastObserved = matchup?.days?.filter(observed).at(-1)?.date;
  const [selected, setSelected] = useState(lastObserved);
  if (!matchup || matchup.unavailable) {
    return <section className="fx-matchup"><Link className="fx-back" to="..">← All matchups</Link><p className="fx-status">This matchup isn't available.</p></section>;
  }
  const teams = [matchup.home, matchup.away], odds = [matchup.chance, 100 - matchup.chance], fav = favorite(matchup);
  return (
    <section className="fx-matchup" aria-label={`${teams[0].name} vs ${teams[1].name}`}>
      <Link className="fx-back" to="..">← All matchups</Link>
      <div className="fx-hero">
        {teams.map((team, side) => (
          <div key={side} className={`fx-hero-team${fav === side ? ' fx-team--fav' : ''}`}>
            <TeamLogo team={team} side={side} size={64} />
            <h2>{team.name}</h2>
            <strong style={{ color: COLORS[side] }}>{round(matchup.scores[side])}</strong>
            <span>{pct(odds[side])} to win · proj. {round(matchup.projected_totals[side])}</span>
          </div>
        ))}
      </div>
      <div className="fx-bar fx-bar--big" aria-hidden="true">
        {odds.map((value, side) => <i key={side} style={{ flex: `${value} 0 0`, background: COLORS[side], opacity: fav === side ? 1 : 0.35 }} />)}
      </div>

      <div className="fx-panel">
        <div className="fx-panel-head"><h3>Score so far and projected</h3><OddsTrend history={matchup.odds_history} /></div>
        <ScorePath matchup={matchup} height={230} />
        <p className="fx-small">Solid lines are actual points; dashed lines project the rest of the week. Likely final margin: {round(matchup.margin_80[0])} to {round(matchup.margin_80[1])}.</p>
      </div>

      <div className="fx-panel">
        <div className="fx-panel-head"><h3>Points by day</h3><span className="fx-small">Tap a day for who scored</span></div>
        <DayBars matchup={matchup} selected={selected} onSelect={setSelected} />
        {selected && <>
          <h3 className="fx-day-title">Who scored · {longDay(selected)}</h3>
          <Players matchup={matchup} date={selected} />
        </>}
      </div>
    </section>
  );
}
