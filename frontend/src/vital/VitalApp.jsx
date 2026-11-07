import React, { useEffect, useState } from 'react';
import SiteHeader from '../components/SiteHeader.jsx';
import { getUrl } from '../api.js';
import '../../../design/cozy-wabi/components.css';
import './vital.css';

export const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
// 2 to 5 AM reads near zero every day; the charts start at 6 AM.
export const HOURS = Array.from({ length: 18 }, (_, i) => i + 6);
const REFRESH_MS = 60000;

export const hourLabel = (h) => `${h % 12 || 12} ${h < 12 || h === 24 ? 'AM' : 'PM'}`;

// Weekday (0 = Monday) and hour in New York, from the API's offset timestamp or the browser clock.
export function newYorkNow(at) {
  if (at) {
    const [y, m, d] = at.slice(0, 10).split('-').map(Number);
    return { day: (new Date(Date.UTC(y, m - 1, d)).getUTCDay() + 6) % 7, hour: Number(at.slice(11, 13)) };
  }
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York', weekday: 'short', hour: 'numeric', hourCycle: 'h23',
  }).formatToParts(new Date()).map((p) => [p.type, p.value]));
  return { day: DAYS.indexOf(parts.weekday), hour: Number(parts.hour) };
}

export function verdict(people, typical) {
  if (typical == null || typical < 10) return null;
  const ratio = people / typical;
  return ratio > 1.15 ? 'Busier than usual' : ratio < 0.85 ? 'Quieter than usual' : 'About usual';
}

// The quietest hour still ahead today, if it beats the count now. Hours under a
// tenth of the day's peak are closing time, not a good time to go (as in busy.py).
export function quietestAhead(hours, hour, people) {
  const open = Math.max(...hours.filter((v) => v != null)) / 10;
  const ahead = HOURS.filter((h) => h > hour && hours[h] != null && hours[h] >= open);
  if (!ahead.length) return null;
  const best = ahead.reduce((a, b) => (hours[b] < hours[a] ? b : a));
  return people == null || hours[best] < people ? { hour: best, people: hours[best] } : null;
}

function useJson(path, every) {
  const [state, setState] = useState({ status: 'loading' });
  useEffect(() => {
    let live = true;
    const load = async () => {
      try {
        const response = await fetch(`${getUrl()}/vital/${path}`);
        const body = await response.json().catch(() => null);
        if (!response.ok) throw new Error(body?.detail || 'Could not reach VITAL.');
        if (live) setState({ status: 'ready', data: body });
      } catch (error) {
        if (live) setState((s) => ({ ...s, status: 'error', message: error.message }));
      }
    };
    load();
    if (!every) return () => { live = false; };
    const timer = setInterval(() => { if (document.visibilityState === 'visible') load(); }, every);
    return () => { live = false; clearInterval(timer); };
  }, [path, every]);
  return state;
}

function Live({ now, week }) {
  if (now.status === 'loading') return <section className="vt-live" aria-busy="true"><p className="cc-caption">Counting…</p></section>;
  if (!now.data) return <section className="vt-live"><p className="cc-notice cc-notice--error" role="alert">{now.message}</p></section>;
  const { people, at, typical } = now.data;
  const { day, hour } = newYorkNow(at);
  const ahead = week && quietestAhead(week.hours[day], hour, people);
  const said = verdict(people, typical);
  return (
    <section className="vt-live" aria-label="Right now">
      <p className="vt-live__count"><b>{people}</b> people now</p>
      <p className="vt-live__compare">
        {said && <span className="vt-verdict" data-verdict={said}>{said}</span>}
        {typical != null && <span>Typical {DAYS[day]} {hourLabel(hour)}: {typical}</span>}
      </p>
      {ahead && <p className="vt-live__ahead">Quietest later today: <b>{hourLabel(ahead.hour)}</b>, about {ahead.people}</p>}
      {now.status === 'error' && <p className="cc-caption" role="status">Couldn't refresh. Showing the {at.slice(11, 16)} count.</p>}
    </section>
  );
}

function DayChart({ hours, top, nowHour, people, day }) {
  const [hover, setHover] = useState(null);
  // Drawn near phone width so the 11px axis text stays 11px.
  const W = 360, H = 190, PAD = { top: 10, right: 4, bottom: 22, left: 30 };
  const step = (W - PAD.left - PAD.right) / HOURS.length;
  const y = (v) => H - PAD.bottom - (v / top) * (H - PAD.top - PAD.bottom);
  const shown = hover ?? nowHour;
  return (
    <figure className="vt-chart">
      <div className="vt-chart__plot">
        <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Typical people by hour on ${DAYS[day]}`}
          onPointerLeave={() => setHover(null)}>
          {[0, top / 2, top].map((t) => (
            <g key={t}>
              <line className="vt-grid" x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} />
              <text className="vt-axis" x={PAD.left - 6} y={y(t) + 4} textAnchor="end">{Math.round(t)}</text>
            </g>
          ))}
          {HOURS.map((h, i) => {
            const v = hours[h] ?? 0;
            const x = PAD.left + i * step;
            return (
              <g key={h} onPointerEnter={() => setHover(h)} onClick={() => setHover(h)}>
                <rect className="vt-hit" x={x} y={PAD.top} width={step} height={H - PAD.top - PAD.bottom} />
                <path className={`vt-bar${h === nowHour ? ' is-now' : ''}${h === hover ? ' is-hover' : ''}`}
                  d={bar(x + 1, y(v), step - 2, H - PAD.bottom - y(v))} />
                {i % 3 === 0 && <text className="vt-axis" x={x + step / 2} y={H - 6} textAnchor="middle">{hourLabel(h)}</text>}
              </g>
            );
          })}
          {nowHour != null && people != null && nowHour >= HOURS[0] && (
            <g className="vt-now">
              <line x1={PAD.left + (nowHour - HOURS[0]) * step} x2={PAD.left + (nowHour - HOURS[0] + 1) * step}
                y1={y(Math.min(people, top))} y2={y(Math.min(people, top))} />
              <circle cx={PAD.left + (nowHour - HOURS[0] + 0.5) * step} cy={y(Math.min(people, top))} r="5" />
            </g>
          )}
        </svg>
      </div>
      <figcaption className="vt-chart__readout" aria-live="polite">
        {shown != null && hours[shown] != null
          ? <><b>{hourLabel(shown)}</b> typically {hours[shown]}{shown === nowHour && people != null ? `, ${people} now` : ''}</>
          : <span>Tap an hour</span>}
      </figcaption>
    </figure>
  );
}

// A bar rounded only at its top, anchored flat to the baseline.
function bar(x, y, w, h) {
  if (h <= 0) return '';
  const r = Math.min(4, w / 2, h);
  return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
}

function Week({ week, day, setDay, top }) {
  return (
    <figure className="vt-week">
      <div className="vt-week__grid" role="grid" aria-label="Typical people by weekday and hour">
        <span />
        {HOURS.map((h) => <span key={h} className="vt-week__hour">{h % 3 === 0 ? hourLabel(h).replace(' ', '') : ''}</span>)}
        {DAYS.map((name, d) => (
          <React.Fragment key={name}>
            {/* The day buttons above are the accessible control; tapping a row is a shortcut. */}
            <span className={`vt-week__day${d === day ? ' is-selected' : ''}`} onClick={() => setDay(d)}>{name}</span>
            {HOURS.map((h) => {
              const v = week.hours[d][h];
              return (
                <span key={h} role="gridcell" className="vt-week__cell" title={`${name} ${hourLabel(h)}: ${v ?? 'no data'}`}
                  aria-label={`${name} ${hourLabel(h)}: ${v ?? 'no data'}`}
                  style={{ '--level': v == null ? 0 : Math.round((v / top) * 100) }} onClick={() => setDay(d)} />
              );
            })}
          </React.Fragment>
        ))}
      </div>
    </figure>
  );
}

export default function VitalApp() {
  const now = useJson('now', REFRESH_MS);
  const week = useJson('week', 0);
  const current = newYorkNow(now.data?.at);
  const [picked, setPicked] = useState(null);
  const day = picked ?? current.day;
  const w = week.data;
  const top = w ? Math.max(...w.hours.flat().filter((v) => v != null)) : 1;
  return (
    <div className="vt-page">
      <SiteHeader product="VITAL" to="/vital" icon="🧗" onSignIn={null} />
      <main className="vt-main">
        <h1 className="cc-h1">VITAL Brooklyn</h1>
        <Live now={now} week={w} />
        {week.status === 'error' && <p className="cc-notice cc-notice--error" role="alert">{week.message}</p>}
        {w && (
          <>
            <section className="vt-section" aria-label="By hour">
              <nav className="cc-segmented vt-days" role="tablist" aria-label="Day">
                {DAYS.map((name, d) => (
                  <button key={name} type="button" role="tab" className="cc-segmented__item" aria-selected={d === day}
                    onClick={() => setPicked(d)}>{name}</button>
                ))}
              </nav>
              <DayChart hours={w.hours[day]} top={top} day={day}
                nowHour={day === current.day ? current.hour : null}
                people={day === current.day ? now.data?.people : null} />
            </section>
            <section className="vt-section" aria-label="Week">
              <h2 className="cc-h3">Week</h2>
              <Week week={w} day={day} setDay={setPicked} top={top} />
              <div className="vt-scale" aria-hidden="true"><span>0</span><i /><span>{top}</span></div>
            </section>
            <details className="cc-accordion">
              <summary>{DAYS[day]} by hour</summary>
              <table className="vt-table">
                <thead><tr><th scope="col">Hour</th><th scope="col">Typical</th></tr></thead>
                <tbody>{HOURS.map((h) => <tr key={h}><th scope="row">{hourLabel(h)}</th><td>{w.hours[day][h] ?? '–'}</td></tr>)}</tbody>
              </table>
            </details>
            <p className="cc-caption">Median of {w.samples.toLocaleString()} counts, {w.from} to {w.to}. Counts include the roof, patio and classes.</p>
          </>
        )}
      </main>
    </div>
  );
}
