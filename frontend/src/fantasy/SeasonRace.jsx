import React, { useState } from 'react';
import { Manager, TeamLogo, pct } from './parts.jsx';
import { seasonRead } from './analysis.js';

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
  const [open, setOpen] = useState(null);
  return (
    <section className="fx-race" aria-label="Race to the playoffs">
      <div className="fx-section-head">
        <h2>Race to the playoffs</h2>
        <span>{season.trials?.toLocaleString()} simulated seasons · {season.weeksRemaining} weeks left</span>
      </div>
      <SeasonRead read={seasonRead(rows)} />
      {available.length > 1 && (
        <div className="fx-modes" role="group" aria-label="Form weighting">
          {available.map(([key, label]) => <button key={key} type="button" aria-pressed={mode === key} onClick={() => setMode(key)}>{label}</button>)}
        </div>
      )}
      {!season.formActive && available.length > 1 && <p className="fx-small">Form starts counting after week 1.</p>}
      <div className="fx-key" aria-hidden="true"><span><i className="fx-key-title" />Win title</span><span><i className="fx-key-playoffs" />Make playoffs</span></div>
      <ol className="fx-race-list" aria-label="Playoff and title chances by team">
        {shown.map(row => {
          const expanded = open === row.team.id;
          return (
            <li key={row.team.id} className={expanded ? 'fx-race-open' : undefined}>
              <button type="button" className="fx-race-row" aria-expanded={expanded} onClick={() => setOpen(expanded ? null : row.team.id)}
                aria-label={`${row.team.name}: ${pct(row.playoff_pct)} playoffs, ${pct(row.title_pct)} title`}>
                <span className="fx-race-team"><TeamLogo team={row.team} side={0} size={26} />
                  <span>{row.team.name}<small><Manager team={row.team} />{row.record?.slice(0, 2).join('–')} · {row.expected_wins} exp. wins</small></span></span>
                <span className="fx-odds-bar" aria-hidden="true">
                  <i className="fx-odds-playoffs" style={{ width: `${row.playoff_pct}%` }} />
                  <i className="fx-odds-title" style={{ width: `${row.title_pct}%` }} />
                </span>
                <span className="fx-race-nums"><b>{pct(row.playoff_pct)}</b><small>playoffs</small></span>
                <span className="fx-race-nums"><b>{pct(row.title_pct)}</b><small>title</small></span>
              </button>
              {expanded && <Finishes row={row} playoffTeams={season.playoffTeams} />}
            </li>
          );
        })}
      </ol>
      {shown.length < rows.length && <button type="button" className="fx-more" onClick={() => setAll(true)}>Show all {rows.length} teams</button>}
      <p className="fx-small">Assumes today’s rosters.</p>
    </section>
  );
}

function SeasonRead({ read }) {
  if (!read) return null;
  return (
    <div className="fx-read">
      <p className="fx-headline"><b>{read.leader}</b> leads. <span>{read.why}.</span></p>
      {!!read.tags.length && <p className="fx-chips">{read.tags.map(tag => <span key={tag} className="fx-chip">{tag}</span>)}</p>}
    </div>
  );
}

function Finishes({ row, playoffTeams }) {
  const peak = Math.max(1, ...row.place_pct);
  return (
    <div className="fx-finish" role="img" aria-label={`${row.team.name} finish chances: ${row.place_pct.map((p, i) => `${ordinal(i + 1)} ${pct(p)}`).join(', ')}`}>
      {row.place_pct.flatMap((p, i) => [i === playoffTeams && <span key="cut" className="fx-finish-cut" aria-hidden="true" />,
        <span key={i} className={`fx-finish-col${i < playoffTeams ? ' fx-finish-in' : ''}`}>
          <small>{Math.round(p)}%</small>
          <i style={{ height: `${Math.max(2, p / peak * 100)}%` }} />
          <b>{ordinal(i + 1)}</b>
        </span>])}
    </div>
  );
}
