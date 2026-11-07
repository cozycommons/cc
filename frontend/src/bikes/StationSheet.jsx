import React from 'react';
import { X } from 'lucide-react';
import { mins, odds, reportedLabel } from './live.js';

const KEY = { bike: 'bikes', ebike: 'ebikes', dock: 'open_docks' };
const NOUN = { bike: 'bike', ebike: 'e-bike', dock: 'dock' };
const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

function how(option, need) {
  if (option.how === 'here') return option.status !== 'available' ? 'Wait here' : need === 'dock' ? 'Dock here' : 'Take one here';
  if (option.how === 'ride') return `Ride ${mins(option.travel_min)}, walk ${mins(option.walk_back_min)} back`;
  return `Walk ${mins(option.travel_min)}`;
}

// The call, in a few words: take one, wait, or go where.
export function headline(result) {
  const { station: here, best, need } = result;
  if (here.status === 'available') return need === 'dock' ? 'Dock here' : 'Take one here';
  if (!best) return `No ${NOUN[need]} nearby soon`;
  if (best.station_id === here.station_id) return `Wait here, about ${mins(here.wait_min)}`;
  return need === 'dock' ? `Ride to ${best.station}` : `Walk to ${best.station}`;
}

function Option({ option, need, best }) {
  const count = option[KEY[need]];
  const facts = [plural(count, NOUN[need]) + ' now'];
  if (option.how !== 'here' && option.chance != null && option.status === 'available') facts.push(`${odds(option.chance)} one is left`);
  if (option.how === 'here' && option.status !== 'available' && option.wait_min != null) facts.push(`next in about ${mins(option.wait_min)}`);
  if (option.status === 'unknown') facts.push('not reporting');
  return (
    <li className={`bk-option${best ? ' is-best' : ''}`}>
      <i className={`bk-option__dot bk-verdict--${option.verdict?.tone ?? 'unknown'}`} aria-hidden="true" />
      <div className="bk-option__body">
        <b>{option.how === 'here' ? how(option, need) : option.station}</b>
        <span>{option.how === 'here' ? facts.join(' · ') : `${how(option, need)} · ${facts.join(' · ')}`}</span>
      </div>
      <span className="bk-option__total" aria-label={`about ${mins(option.expected_min)} in all`}>
        {option.expected_min == null ? '—' : mins(option.expected_min)}
      </span>
    </li>
  );
}

// One line weighing the call against waiting here.
export function comparison(result) {
  const { station: here, best } = result;
  if (here.status === 'available' || !best) return null;
  if (best.station_id === here.station_id) return 'Nothing nearby is faster.';
  const total = `About ${mins(best.expected_min)} in all`;
  if (here.status === 'unknown') return `${total}. This station is not reporting.`;
  return here.expected_min == null ? `${total}. Here, rarely any at this hour.` : `${total}, vs about ${mins(here.expected_min)} waiting here.`;
}

// Standing at a station: wait for a bike (or dock), or walk (ride) to the next one?
// `result` is /bikes/options for that station; the map draws the same options as routes.
export default function StationSheet({ result, need, onClose, onStartHere, onPlan }) {
  const here = result.station;
  const counts = need === 'dock'
    ? `${plural(here.open_docks, 'open dock')} · ${plural(here.bikes, 'bike')}`
    : `${here.bikes - here.ebikes} classic · ${plural(here.ebikes, 'e-bike')} · ${plural(here.open_docks, 'dock')}`;
  const place = { name: here.station, lat: here.lat, lng: here.lng };
  return (
    <div className="bk-sheet__station" role="region" aria-label={`At ${here.station}`}>
      <div className="bk-sheet__head">
        <div>
          <p className="bk-sheet__kicker">{need === 'dock' ? 'Need a dock here?' : 'Need a bike here?'}</p>
          <h2>{here.station}</h2>
          <p className="bk-data">{counts}{here.reported_s != null ? ` · ${reportedLabel(here.reported_s).toLowerCase()}` : ''}</p>
        </div>
        <button type="button" className="bk-from__clear" onClick={onClose} aria-label="Close"><X size={18} aria-hidden="true" /></button>
      </div>
      <p className="bk-verdict">{headline(result)}</p>
      {comparison(result) && <p className="bk-data">{comparison(result)}</p>}
      <ol className="bk-options">
        {result.options.map((o) => (
          <Option key={o.station_id} option={o} need={need} best={o.station_id === result.best?.station_id} />
        ))}
      </ol>
      <div className="bk-pop__actions">
        <button type="button" className="cc-button cc-button--small" onClick={() => onStartHere(place)}>Start from here</button>
        <button type="button" className="cc-button cc-button--small cc-button--secondary" onClick={() => onPlan('from', place)}>Plan from here</button>
        <button type="button" className="cc-button cc-button--small cc-button--secondary" onClick={() => onPlan('to', place)}>Plan to here</button>
      </div>
    </div>
  );
}
