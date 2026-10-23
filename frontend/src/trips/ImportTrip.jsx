import React, { useRef, useState } from 'react';
import { Field, Form } from './ui.jsx';
import { money } from './money.js';

export default function ImportTrip({ request, onImported, onCancel }) {
  const [snapshot, setSnapshot] = useState(null);
  const [ownMember, setOwnMember] = useState('');
  const [preview, setPreview] = useState(null);
  const [fileError, setFileError] = useState('');
  const [reading, setReading] = useState(false);
  const readVersion = useRef(0);
  return <Form submit={reading ? 'Reading file…' : preview ? preview.status === 'existing' ? 'Open existing trip' : 'Import trip' : 'Preview import'} onCancel={onCancel} onSubmit={async () => {
    if (reading) throw new Error('Wait for the file to finish loading.');
    if (!snapshot || !ownMember) throw new Error('Choose a trip snapshot and your person before previewing.');
    const payload = { snapshot, own_member_id: ownMember };
    if (!preview) {
      setPreview(await request('/imports/preview', 'POST', payload));
    } else if (preview.status === 'existing') {
      onImported(preview.group);
    } else {
      const saved = await request('/imports', 'POST', payload);
      onImported(saved.group);
    }
  }}>
    <p className="trips-muted">Bring over a captured Splitwise trip. Review its people and balances before saving.</p>
    <Field label="Splitwise trip snapshot" hint="Choose a Cozy Trips Splitwise JSON snapshot, up to 5 MB."><input type="file" accept=".json,application/json" onChange={async (event) => {
      const file = event.target.files?.[0];
      const version = ++readVersion.current;
      setSnapshot(null); setPreview(null); setOwnMember(''); setFileError('');
      setReading(false);
      if (!file) return;
      if (file.size > 5 * 1024 * 1024) { setFileError('Choose a snapshot smaller than 5 MB.'); return; }
      setReading(true);
      try {
        const parsed = JSON.parse(await file.text());
        if (version !== readVersion.current) return;
        if (parsed.format !== 'cozy-trips-splitwise-v1' || !Array.isArray(parsed.members) || !parsed.members.length || parsed.members.some(m => typeof m.id !== 'string' || typeof m.name !== 'string')) {
          throw new Error('Unsupported snapshot');
        }
        setSnapshot(parsed);
      } catch { if (version === readVersion.current) setFileError('Choose a valid Cozy Trips Splitwise snapshot file.'); }
      finally { if (version === readVersion.current) setReading(false); }
    }} /></Field>
    {fileError && <p role="alert" className="trips-error">{fileError}</p>}
    {snapshot && <Field label="Your person in Splitwise" hint="Other people keep their shares and can claim their place through an invitation."><select required value={ownMember} onChange={event => { setOwnMember(event.target.value); setPreview(null); }}>
      <option value="">Choose your name</option>{snapshot.members.map((member, index) => <option key={member.id} value={member.id}>{member.name}{snapshot.members.filter(m => m.name === member.name).length > 1 ? ` · person ${index + 1}` : ''}</option>)}
    </select></Field>}
    {preview && <section className="trips-import-preview" aria-label="Import preview">
      <h3>{preview.group.name}</h3>
      <p>{preview.report.expense_count} expenses · {preview.report.repayment_count} repayments · {preview.report.currency}</p>
      <p role="status">{preview.status === 'existing' ? 'This snapshot is already imported. Your current Trips edits will be kept.' : 'Every source balance matches. Ready to import.'}</p>
      <table><caption>{preview.status === 'existing' ? 'Current trip balances' : 'Reconciled source balances'}</caption><thead><tr><th scope="col">Person</th><th scope="col">Balance</th></tr></thead>
        <tbody>{preview.group.members.map(member => <tr key={member.id}><th scope="row">{member.name}</th><td>{money(preview.group.balances[member.id], preview.group.currency)}</td></tr>)}</tbody>
      </table>
    </section>}
  </Form>;
}
