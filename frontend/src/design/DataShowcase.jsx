import React from 'react';
import { ComparisonBar, DataRow, SegmentedControl, Skeleton } from './system/DataPatterns.jsx';

const periods = [
  { value: 'week', label: 'Week' },
  { value: 'month', label: 'Month' },
  { value: 'season', label: 'Season' },
];
const records = { week: [18, 6], month: [64, 28], season: [142, 76] };

export default function DataShowcase() {
  const [period, setPeriod] = React.useState('week');
  const [loading, setLoading] = React.useState(false);
  const [updated, setUpdated] = React.useState(false);
  const timer = React.useRef();
  React.useEffect(() => () => window.clearTimeout(timer.current), []);
  const refresh = () => {
    setLoading(true);
    timer.current = window.setTimeout(() => { setLoading(false); setUpdated(true); }, 1200);
  };
  const [played, remaining] = records[period];
  return <section className="cc-section cc-data-showcase" id="data-patterns" aria-labelledby="data-patterns-title">
    <div className="cc-section-heading cc-section-heading--compact">
      <div><p className="cc-kicker"><span className="cc-kicker__dot" aria-hidden="true" />New / data & interaction</p><h2 className="cc-h2" id="data-patterns-title">Numbers, with context.</h2></div>
      <p className="cc-section-heading__aside">Sample data · interactive specimens</p>
    </div>
    <div className="cc-data-grid">
      <article className="cc-data-panel">
        <div className="cc-data-panel__heading"><span className="cc-label">01 / selection & comparison</span><span className="cc-data-tag">Interactive</span></div>
        <SegmentedControl label="Record period" options={periods} value={period} onChange={setPeriod} />
        <div className="cc-data-metric"><strong>{played}<span> / {played + remaining}</span></strong><span>games played</span></div>
        <ComparisonBar label="Schedule completion" value={played} total={played + remaining} leftLabel={`${played} played`} rightLabel={`${remaining} remaining`} />
        <p className="cc-data-caption">One selection changes the view. Labels keep the bar readable without relying on color.</p>
      </article>
      <article className="cc-data-panel">
        <div className="cc-data-panel__heading"><span className="cc-label">02 / expandable rows</span><span className="cc-data-tag">Open a row</span></div>
        <h3 className="cc-h3">Weekend ledger</h3>
        <div className="cc-data-list">
          <DataRow title="Groceries" subtitle="3 purchases" value="$84.20"><dl><div><dt>Market</dt><dd>$42.00</dd></div><div><dt>Bakery</dt><dd>$18.20</dd></div><div><dt>Corner store</dt><dd>$24.00</dd></div></dl></DataRow>
          <DataRow title="Transport" subtitle="2 rides" value="$32.00"><dl><div><dt>Station → house</dt><dd>$18.00</dd></div><div><dt>House → station</dt><dd>$14.00</dd></div></dl></DataRow>
          <DataRow title="Dinner" subtitle="Split between 4" value="$96.00"><p>$24.00 per person. All four shares are included.</p></DataRow>
        </div>
        <p className="cc-data-caption">A summary stays visible while its supporting details open underneath.</p>
      </article>
      <article className="cc-data-panel cc-data-panel--refresh">
        <div className="cc-data-panel__heading"><span className="cc-label">03 / loading & freshness</span><span className={`cc-data-tag${loading ? ' cc-data-tag--busy' : ''}`}>{loading ? 'Updating' : 'Sample'}</span></div>
        <div className="cc-refresh-layout">
          <div><h3 className="cc-h3">Keep your place.</h3><p className="cc-data-caption">Keep the last result during a refresh. Use a skeleton for the first load.</p><button className="cc-button cc-button--secondary" type="button" disabled={loading} onClick={refresh}>{loading ? 'Refreshing…' : 'Preview refresh'}</button><p className="cc-data-caption" role="status">{loading ? 'Fetching sample update…' : updated ? 'Sample updated just now.' : 'Ready to preview.'}</p></div>
          <div className="cc-refresh-sample"><div className="cc-refresh-sample__heading"><span>Weekly activity</span><strong>24 games</strong></div><div aria-busy={loading}>{loading ? <Skeleton label="Loading sample activity" /> : <div className="cc-mini-bars" aria-label="Sample activity: Monday 4, Tuesday 7, Wednesday 5, Thursday 8 games" role="img">{[4, 7, 5, 8].map((value, index) => <div key={index}><i style={{ height: `${value * 10}px` }} /><span>{['M', 'T', 'W', 'T'][index]}</span></div>)}</div>}</div></div>
        </div>
      </article>
    </div>
  </section>;
}
