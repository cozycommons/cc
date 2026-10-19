import React from 'react';
import { ArrowLeft } from 'lucide-react';
import { eventDate, possibleDuplicates } from './setDetails';

const deviceZone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
const timezones = [...new Set([deviceZone, 'UTC', ...(Intl.supportedValuesOf?.('timeZone') || [])])];

export default function CreateSet({ sets, structured, busy, onCreate, onChoose, onBack }) {
  const [fields, setFields] = React.useState({ name: '', artist: '', venue: '', starts_at: '', ends_at: '', timezone: deviceZone });
  const [draft, setDraft] = React.useState(null);
  const [validation, setValidation] = React.useState('');
  const matches = draft ? possibleDuplicates(sets, draft) : [];
  const change = (event) => { setFields((previous) => ({ ...previous, [event.target.name]: event.target.value })); setValidation(''); };

  function submit(event) {
    event.preventDefault();
    if (structured && fields.ends_at <= fields.starts_at) { setValidation('End must be after start.'); return; }
    const value = structured ? { name: fields.artist.trim(), artist: fields.artist.trim(), venue: fields.venue.trim(), starts_at: fields.starts_at, ends_at: fields.ends_at, timezone: fields.timezone } : { name: fields.name.trim() };
    if (structured ? !value.artist || !value.venue : !value.name) { setValidation('Enter the set details.'); return; }
    if (possibleDuplicates(sets, value).length) setDraft(value);
    else onCreate(value);
  }

  return <section className="cs-create">
    <button className="cs-back" disabled={busy} onClick={onBack}><ArrowLeft size={17} /> Sets</button>
    <h1>New set</h1>
    {draft && matches.length ? <div className="cs-duplicate">
      <h2>Possible duplicate</h2>
      {matches.map((set) => <button className="cs-duplicate-set" disabled={busy} key={set.id} onClick={() => onChoose(set)}>
        <strong>{set.artist || set.name}</strong><span>{[set.venue, eventDate(set)].filter(Boolean).join(' · ')}</span><span>Open set →</span>
      </button>)}
      <button className="cs-primary" disabled={busy} onClick={() => onCreate(draft)}>{busy ? 'Creating…' : 'Create a different set'}</button>
      <button className="cs-text-button" disabled={busy} onClick={() => setDraft(null)}>Edit details</button>
    </div> : <form onSubmit={submit} className="cs-new-set">
      {structured ? <>
        <label>Artist<input name="artist" autoFocus required maxLength={120} value={fields.artist} onChange={change} disabled={busy} /></label>
        <label>Venue<input name="venue" required maxLength={160} placeholder="Venue and city" value={fields.venue} onChange={change} disabled={busy} /></label>
        <div className="cs-field-pair">
          <label>Start<input name="starts_at" type="datetime-local" required value={fields.starts_at} onInput={change} onChange={change} disabled={busy} /></label>
          <label>End<input name="ends_at" type="datetime-local" required min={fields.starts_at || undefined} value={fields.ends_at} onInput={change} onChange={change} disabled={busy} /></label>
        </div>
        <label>Time zone<select name="timezone" value={fields.timezone} onChange={change} disabled={busy}>{timezones.map((zone) => <option key={zone} value={zone}>{zone.replaceAll('_', ' ')}</option>)}</select></label>
      </> : <label>Set name<input name="name" autoFocus required placeholder="Artist · venue · date" maxLength={120} value={fields.name} onChange={change} disabled={busy} /></label>}
      {validation && <p role="alert" className="cs-field-error">{validation}</p>}
      <p className="cs-meta">Public · Signed-in members</p>
      <button className="cs-primary" disabled={busy || !(structured ? fields.artist.trim() && fields.venue.trim() && fields.starts_at && fields.ends_at : fields.name.trim())}>{busy ? 'Creating…' : 'Create set'}</button>
    </form>}
  </section>;
}
