import React from 'react';
import { X } from 'lucide-react';
import { mins, odds, reportedLabel, usePolling } from './live.js';

const KEY = { bike: 'bikes', ebike: 'ebikes', dock: 'open_docks' };
const NOUN = { bike: 'bike', ebike: 'e-bike', dock: 'dock' };
const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;

function how(option) {
  if (option.how === 'here') return 'Wait here';
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
        <b>{option.how === 'here' ? how(option) : option.station}</b>
        <span>{option.how === 'here' ? facts.join(' · ') : `${how(option)} · ${facts.join(' · ')}`}</span>
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
export default function StationSheet({ stationId, need, onClose, onStartHere, onPlan }) {
  const options = usePolling('options', { station: stationId, need }, true);
  const result = options.data?.station?.station_id === stationId ? options.data : null;
  const here = result?.station;
  const counts = here && (need === 'dock'
    ? `${plural(here.open_docks, 'open dock')} · ${plural(here.bikes, 'bike')}`
    : `${here.bikes - here.ebikes} classic · ${plural(here.ebikes, 'e-bike')} · ${plural(here.open_docks, 'dock')}`);
  const place = here && { name: here.station, lat: here.lat, lng: here.lng };
  return (
    <aside className="bk-sheet" role="dialog" aria-label={here ? `At ${here.station}` : 'Station'}>
      <div className="bk-sheet__head">
        <div>
          <p className="bk-sheet__kicker">{need === 'dock' ? 'Need a dock here?' : 'Need a bike here?'}</p>
          <h2>{here?.station ?? 'Checking…'}</h2>
          {here && <p className="bk-data">{counts}{here.reported_s != null ? ` · ${reportedLabel(here.reported_s).toLowerCase()}` : ''}</p>}
        </div>
        <button type="button" className="bk-from__clear" onClick={onClose} aria-label="Close"><X size={18} aria-hidden="true" /></button>
      </div>
      {options.status === 'error' && !result && <p className="cc-notice cc-notice--error" role="alert">{options.message}</p>}
      {result && (
        <>
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
        </>
      )}
    </aside>
  );
}
