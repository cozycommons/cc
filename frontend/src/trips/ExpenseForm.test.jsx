import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { ExpenseForm } from './TripsApp.jsx';

afterEach(cleanup);

const members = [{ id: 'matt', user_id: 'user-matt', name: 'Matt' }, { id: 'alex', name: 'Alex' }, { id: 'jamie', name: 'Jamie' }];
const group = { revision: 7, currency: 'USD', members };

it('exposes stable native labels and preserves a mismatched exact-split draft', async () => {
  const save = vi.fn().mockResolvedValue(undefined);
  render(<ExpenseForm group={group} user={{ id: 'user-matt' }} onSave={save} onCancel={() => {}} />);
  fireEvent.change(screen.getByLabelText('Description', { exact: true }), { target: { value: 'Dinner' } });
  fireEvent.change(screen.getByLabelText('Amount (USD)', { exact: true }), { target: { value: '90' } });
  fireEvent.change(screen.getByLabelText('Category', { exact: true }), { target: { value: 'food' } });
  fireEvent.change(screen.getByLabelText('Paid by', { exact: true }), { target: { value: 'alex' } });
  fireEvent.click(screen.getByRole('button', { name: 'Exact amounts', exact: true }));
  for (const name of ['Matt', 'Alex', 'Jamie']) {
    fireEvent.change(screen.getByRole('textbox', { name: `Share for ${name} (USD)` }), { target: { value: '20' } });
  }
  fireEvent.click(screen.getByRole('button', { name: 'Save expense' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Exact shares must add up');
  expect(save).not.toHaveBeenCalled();
  expect(screen.getByLabelText('Description', { exact: true })).toHaveValue('Dinner');
  fireEvent.change(screen.getByRole('textbox', { name: 'Share for Matt (USD)' }), { target: { value: '30' } });
  fireEvent.change(screen.getByRole('textbox', { name: 'Share for Alex (USD)' }), { target: { value: '40' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save expense' }));
  await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
  expect(save.mock.calls[0][0]).toMatchObject({ amount_minor: 9000, revision: 7, paid_by: 'alex', category: 'food', shares: { matt: 3000, alex: 4000, jamie: 2000 } });
});
