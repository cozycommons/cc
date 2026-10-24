import React, { useState } from 'react';
import { TeamLogo, pct } from './parts.jsx';

const MODES = [['projections', 'Projections only'], ['balanced', 'Balanced'], ['hot', 'Hot hand']];
const ordinal = n => `${n}${n === 1 ? 'st' : n === 2 ? 'nd' : n === 3 ? 'rd' : 'th'}`;

export function rankTeams(rows) {
  return [...rows].sort((a, b) => b.title_pct - a.title_pct || b.playoff_pct - a.playoff_pct);
}

export default function SeasonRace({ season, narrow }) {
  const available = MODES.filter(([key]) => season.modes[key]);
  const [mode, setMode] = useState(season.modes.balanced ? 'balanced' : available[0][0]);
  const [all, setAll] = useState(false);
  const rows = rankTeams(season.modes[mode]);
  const shown = narrow && !all ? rows.slice(0, season.playoffTeams) : rows;
  const leader = rows[0];
  // Shade relative to the most likely finish in the table so early-season odds stay visible.
  const peak = Math.max(1, ...rows.flatMap(row => row.place_pct));
  return (
    <section className="fx-race" aria-label="Race to the playoffs">
      <div className="fx-section-head">
        <h2>Race to the playoffs</h2>
        <span>{season.trials?.toLocaleString()} simulated seasons · {season.weeksRemaining} weeks left</span>
      </div>
      <p className="fx-headline">{leader.team.name} is the title favorite at {pct(leader.title_pct)}.</p>
      {available.length > 1 && (
        <div className="fx-modes" role="group" aria-label="Form weighting">
          {available.map(([key, label]) => <button key={key} type="button" aria-pressed={mode === key} onClick={() => setMode(key)}>{label}</button>)}
        </div>
      )}
      {!season.formActive && available.length > 1 && <p className="fx-small">Form kicks in after the first completed week; all three settings match until then.</p>}
      <div className="fx-race-table" role="table" aria-label="Finishing chances by team">
        <div className="fx-race-row fx-race-labels" role="row">
          <span role="columnheader">Team</span><span role="columnheader">Finish 1st → last</span>
          <span role="columnheader">Playoffs</span><span role="columnheader">Title</span>
        </div>
        {shown.map(row => (
          <div className="fx-race-row" role="row" key={row.team.id}>
            <span className="fx-race-team" role="cell"><TeamLogo team={row.team} side={0} size={24} />
              <span>{row.team.name}<small>{row.record?.slice(0, 2).join('–')} · {row.expected_wins} exp. wins</small></span></span>
            <span role="cell" className="fx-strip" aria-label={`${row.team.name}: ${row.place_pct.map((p, i) => `${ordinal(i + 1)} ${pct(p)}`).join(', ')}`}>
              {row.place_pct.flatMap((p, i) => [i === season.playoffTeams && <b key="cut" className="fx-cut" aria-hidden="true" />,
                <i key={i} title={`${ordinal(i + 1)}: ${pct(p)}`} style={{ background: `rgba(183,95,65,${(0.08 + 0.92 * p / peak).toFixed(3)})` }} />])}
            </span>
            <b role="cell">{pct(row.playoff_pct)}</b>
            <b role="cell">{pct(row.title_pct)}</b>
          </div>
        ))}
      </div>
      {shown.length < rows.length && <button type="button" className="fx-more" onClick={() => setAll(true)}>Show all {rows.length} teams</button>}
      <p className="fx-small">Darker = more likely. The gap marks the playoff line (top {season.playoffTeams}). Rosters held as they are today.</p>
    </section>
  );
}
