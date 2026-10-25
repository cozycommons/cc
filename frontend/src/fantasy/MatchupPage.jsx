import React, { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { favorite } from './paths.js';
import { finished, matchupRead, notableSwings, playerSwings } from './analysis.js';
import { COLORS, Manager, OddsTrend, ScorePath, TeamLogo, longDay, round, weekday, winPct } from './parts.jsx';

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
                <img src={headshot(player.id)} alt="" loading="lazy" referrerPolicy="no-referrer" onError={hideBroken} />
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

const headshot = id => `https://a.espncdn.com/i/headshots/nba/players/full/${id}.png`;
const hideBroken = event => { event.currentTarget.style.visibility = 'hidden'; };

function Read({ read }) {
  return (
    <p className="fx-read fx-chips" style={{ '--fx-side': read.side == null ? '#5c4a3d' : COLORS[read.side] }}>
      <b>{read.headline}</b>{read.facts.map(fact => <span key={fact} className="fx-chip">{fact}</span>)}
    </p>
  );
}

function SwingRow({ row }) {
  const tone = row.diff >= 0 ? 'hot' : 'cold';
  return (
    <li className={`fx-swing fx-swing--${tone}`}>
      <img src={headshot(row.id)} alt="" loading="lazy" referrerPolicy="no-referrer" onError={hideBroken} />
      <span>{row.name}<small>{round(row.actual)} of {round(row.expected)} expected{row.games > 1 ? ` · ${row.games} games` : ''}</small></span>
      <b>{row.diff >= 0 ? '+' : '−'}{Math.abs(round(row.diff))}</b>
    </li>
  );
}

// Who is beating or missing their expected points, on finished days only.
function Swings({ matchup, teams }) {
  const sides = playerSwings(matchup);
  if (!sides.some(rows => rows.length)) return null;
  return (
    <div className="fx-panel">
      <div className="fx-panel-head"><h3>Who’s swinging it</h3><span className="fx-small">Finished games vs expected</span></div>
      <div className="fx-swing-teams">
        {sides.map((rows, side) => {
          const { cold, hot } = notableSwings(rows);
          const named = [...cold, ...hot];
          const rest = [...rows].sort((a, b) => a.diff - b.diff).filter(row => !named.includes(row));
          return (
            <div key={side}>
              <h4><TeamLogo team={teams[side]} side={side} size={22} />{teams[side].name}</h4>
              {named.length ? <ul>{named.map(row => <SwingRow key={row.id} row={row} />)}</ul>
                : <p className="fx-small">Everyone close to expected.</p>}
              {!!rest.length && (
                <details className="fx-fold">
                  <summary>{rest.length} more</summary>
                  <ul>{rest.map(row => <SwingRow key={row.id} row={row} />)}</ul>
                </details>
              )}
            </div>
          );
        })}
      </div>
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
            <Manager team={team} />
            <strong style={{ color: COLORS[side] }}>{round(matchup.scores[side])}</strong>
            <span>{winPct(odds[side], finished(matchup))} to win from here · proj. {round(matchup.projected_totals[side])}</span>
          </div>
        ))}
      </div>
      <div className="fx-bar fx-bar--big" aria-hidden="true">
        {odds.map((value, side) => <i key={side} style={{ flex: `${value} 0 0`, background: COLORS[side], opacity: fav === side ? 1 : 0.35 }} />)}
      </div>
      <Read read={matchupRead(matchup)} />
      <Swings matchup={matchup} teams={teams} />

      <div className="fx-panel">
        <div className="fx-panel-head"><h3>Score so far and projected</h3><OddsTrend history={matchup.odds_history} wide /></div>
        <ScorePath matchup={matchup} height={230} />
        <p className="fx-small">Likely final margin: {round(matchup.margin_80[0])} to {round(matchup.margin_80[1])}.</p>
      </div>

      <div className="fx-panel">
        <div className="fx-panel-head"><h3>Points by day</h3></div>
        <DayBars matchup={matchup} selected={selected} onSelect={setSelected} />
        {selected && <>
          <h3 className="fx-day-title">Who scored · {longDay(selected)}</h3>
          <Players matchup={matchup} date={selected} />
        </>}
      </div>
    </section>
  );
}
