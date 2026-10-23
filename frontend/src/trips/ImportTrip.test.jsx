import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import ImportTrip from './ImportTrip.jsx';

afterEach(cleanup);
const snapshot = { format: 'cozy-trips-splitwise-v1', members: [{ id: 'a', name: 'Ari' }, { id: 'b', name: 'Bo' }] };
const preview = { status: 'preview', report: { expense_count: 2, repayment_count: 1, currency: 'USD' },
  group: { id: 'trip-1', name: 'Synthetic trip', currency: 'USD', members: [{ id: 'm1', name: 'Ari' }, { id: 'm2', name: 'Bo' }], balances: { m1: 268, m2: -268 } } };
function fileWith(text) {
  const file = new File([text], 'trip.json', { type: 'application/json' });
  Object.defineProperty(file, 'text', { value: () => Promise.resolve(text) });
  return file;
}
async function chooseSnapshot(value = snapshot) {
  fireEvent.change(screen.getByLabelText('Splitwise trip snapshot'), { target: { files: [fileWith(JSON.stringify(value))] } });
  const select = await screen.findByLabelText('Your person in Splitwise');
  fireEvent.change(select, { target: { value: 'a' } });
}

it('previews before saving, displays all balances, and explicitly maps the current person', async () => {
  const request = vi.fn().mockResolvedValueOnce(preview).mockResolvedValueOnce({ group: preview.group });
  const imported = vi.fn();
  render(<ImportTrip request={request} onImported={imported} onCancel={() => {}} />);
  await chooseSnapshot();
  fireEvent.click(screen.getByRole('button', { name: 'Preview import' }));
  expect(await screen.findByRole('region', { name: 'Import preview' })).toHaveTextContent('Every source balance matches');
  expect(screen.getByRole('table')).toHaveTextContent('$2.68');
  expect(screen.getByRole('table')).toHaveTextContent('-$2.68');
  expect(request).toHaveBeenCalledTimes(1);
  expect(request).toHaveBeenCalledWith('/imports/preview', 'POST', { snapshot, own_member_id: 'a' });
  expect(imported).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'Import trip', exact: true }));
  await waitFor(() => expect(imported).toHaveBeenCalledWith(preview.group));
  expect(request).toHaveBeenLastCalledWith('/imports', 'POST', { snapshot, own_member_id: 'a' });
});

it('opens an existing import while retaining current edits without another save', async () => {
  const request = vi.fn().mockResolvedValue({ ...preview, status: 'existing' });
  const imported = vi.fn();
  render(<ImportTrip request={request} onImported={imported} onCancel={() => {}} />);
  await chooseSnapshot();
  fireEvent.click(screen.getByRole('button', { name: 'Preview import' }));
  fireEvent.click(await screen.findByRole('button', { name: 'Open existing trip' }));
  await waitFor(() => expect(imported).toHaveBeenCalledWith(preview.group));
  expect(request).toHaveBeenCalledTimes(1);
});

it('retains the chosen snapshot and identity after a server validation error', async () => {
  const request = vi.fn().mockRejectedValueOnce(new Error('Import does not reconcile')).mockResolvedValueOnce(preview);
  render(<ImportTrip request={request} onImported={() => {}} onCancel={() => {}} />);
  await chooseSnapshot();
  fireEvent.click(screen.getByRole('button', { name: 'Preview import' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('does not reconcile');
  expect(screen.getByLabelText('Your person in Splitwise')).toHaveValue('a');
  fireEvent.click(screen.getByRole('button', { name: 'Preview import' }));
  expect(await screen.findByRole('region', { name: 'Import preview' })).toHaveTextContent('Synthetic trip');
});

it.each(['not-json', JSON.stringify({ format: 'unknown', members: [] })])('rejects unsupported files without sending them', async value => {
  const request = vi.fn();
  render(<ImportTrip request={request} onImported={() => {}} onCancel={() => {}} />);
  fireEvent.change(screen.getByLabelText('Splitwise trip snapshot'), { target: { files: [fileWith(value)] } });
  expect(await screen.findByRole('alert')).toHaveTextContent('valid Cozy Trips Splitwise snapshot');
  expect(request).not.toHaveBeenCalled();
});

it('rejects oversized files before reading them', async () => {
  const file = fileWith('{}');
  Object.defineProperty(file, 'size', { value: 5 * 1024 * 1024 + 1 });
  render(<ImportTrip request={vi.fn()} onImported={() => {}} onCancel={() => {}} />);
  fireEvent.change(screen.getByLabelText('Splitwise trip snapshot'), { target: { files: [file] } });
  expect(await screen.findByRole('alert')).toHaveTextContent('smaller than 5 MB');
});

it('cancels without making an API request', () => {
  const request = vi.fn(), cancel = vi.fn();
  render(<ImportTrip request={request} onImported={() => {}} onCancel={cancel} />);
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  expect(cancel).toHaveBeenCalledTimes(1);
  expect(request).not.toHaveBeenCalled();
});
