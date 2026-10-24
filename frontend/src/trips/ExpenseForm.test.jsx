import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { ExpenseForm } from './ExpenseForm.jsx';

afterEach(() => { cleanup(); localStorage.clear(); });

const members = [{ id: 'matt', user_id: 'user-matt', name: 'Matt' }, { id: 'alex', name: 'Alex' }, { id: 'jamie', name: 'Jamie' }];
const group = { revision: 7, currency: 'USD', members };
const form = (props = {}) => {
  const save = vi.fn().mockResolvedValue(undefined);
  render(<ExpenseForm group={group} user={{ id: 'user-matt' }} onSave={save} onCancel={() => {}} {...props} />);
  return save;
};
const fill = (description, amount) => {
  fireEvent.change(screen.getByLabelText('Description'), { target: { value: description } });
  fireEvent.change(screen.getByLabelText('Amount (USD)'), { target: { value: amount } });
};

it('exposes native controls and preserves a mismatched exact-split draft', async () => {
  const save = form();
  fill('Dinner', '90');
  fireEvent.click(screen.getByRole('radio', { name: 'Food' }));
  fireEvent.click(screen.getByRole('radio', { name: 'Alex' }));
  fireEvent.click(screen.getByRole('radio', { name: 'Exact amounts' }));
  for (const name of ['Matt', 'Alex', 'Jamie']) {
    fireEvent.change(screen.getByRole('textbox', { name: `Amount for ${name} (USD)` }), { target: { value: '20' } });
  }
  expect(screen.getByText('$30.00 left to assign')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Save expense' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('must add up to $90.00 ($30.00 left)');
  expect(save).not.toHaveBeenCalled();
  expect(screen.getByLabelText('Description')).toHaveValue('Dinner');
  fireEvent.change(screen.getByRole('textbox', { name: 'Amount for Matt (USD)' }), { target: { value: '30' } });
  fireEvent.change(screen.getByRole('textbox', { name: 'Amount for Alex (USD)' }), { target: { value: '40' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save expense' }));
  await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
  expect(save.mock.calls[0][0]).toMatchObject({ amount_minor: 9000, revision: 7, paid_by: 'alex', category: 'food', split_mode: 'exact', shares: { matt: 3000, alex: 4000, jamie: 2000 } });
});

it('defaults the payer to me and selects people quickly', async () => {
  const save = form();
  fill('Coffee', '$12');
  expect(screen.getByRole('radio', { name: 'You' })).toBeChecked();
  fireEvent.click(screen.getByRole('button', { name: 'Just me' }));
  expect(screen.getByText('1 of 3')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('checkbox', { name: 'Jamie' }));
  fireEvent.click(screen.getByRole('button', { name: 'Save expense' }));
  await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
  // Participants are sent in member order regardless of click order.
  expect(save.mock.calls[0][0]).toMatchObject({ amount_minor: 1200, paid_by: 'matt', participants: ['matt', 'jamie'], split_mode: 'equal', shares: {} });
  fireEvent.click(screen.getByRole('checkbox', { name: 'Matt (you)' }));
  fireEvent.click(screen.getByRole('checkbox', { name: 'Jamie' }));
  fireEvent.click(screen.getByRole('button', { name: 'Save expense' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Choose at least one person');
});

it('splits by shares with steppers and previews exact cents', async () => {
  const save = form();
  fill('Cabin', '100');
  fireEvent.click(screen.getByRole('radio', { name: 'By shares' }));
  fireEvent.click(screen.getByRole('button', { name: 'More shares for Matt' }));
  expect(screen.getByRole('textbox', { name: 'Shares for Matt' })).toHaveValue('2');
  expect(screen.getByText('$50.00')).toBeInTheDocument();
  expect(screen.getAllByText('$25.00')).toHaveLength(2);
  fireEvent.click(screen.getByRole('button', { name: 'Save expense' }));
  await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
  expect(save.mock.calls[0][0]).toMatchObject({ split_mode: 'shares', shares: { matt: 2, alex: 1, jamie: 1 } });
});

it('reopens a shares expense with its weights and offers delete inside the editor', () => {
  const onDelete = vi.fn();
  form({ onDelete, expense: { id: 'e1', description: 'Cabin', amount_minor: 10000, paid_by: 'alex', date: '2026-10-20', category: 'stay', notes: 'two nights',
    split_mode: 'shares', shares: { matt: 5000, alex: 5000 }, weights: { matt: 1, alex: 1 } } });
  expect(screen.getByRole('radio', { name: 'By shares' })).toBeChecked();
  expect(screen.getByRole('checkbox', { name: 'Jamie' })).not.toBeChecked();
  expect(screen.getByLabelText('Note (optional)')).toHaveValue('two nights');
  fireEvent.click(screen.getByRole('button', { name: 'Delete' }));
  expect(onDelete).toHaveBeenCalledOnce();
});

it('accepts an unsaved prefill from a link but ignores unknown people', () => {
  form({ initial: { description: 'Gas', amount: '42.50', paid_by: 'jamie', participants: ['alex', 'nobody'], category: 'transport' } });
  expect(screen.getByLabelText('Description')).toHaveValue('Gas');
  expect(screen.getByLabelText('Amount (USD)')).toHaveValue('42.50');
  expect(screen.getByRole('radio', { name: 'Jamie' })).toBeChecked();
  expect(screen.getByRole('radio', { name: 'Transport' })).toBeChecked();
  expect(screen.getByText('1 of 3')).toBeInTheDocument();
});

it('always starts a new expense as you paid, split with everyone, whatever was saved before', async () => {
  const save = form({ group: { ...group, id: 'trip-1' } });
  fill('Tacos', '30');
  fireEvent.click(screen.getByRole('radio', { name: 'Alex' }));
  fireEvent.click(screen.getByRole('checkbox', { name: 'Jamie' }));
  fireEvent.click(screen.getByRole('button', { name: 'Save expense' }));
  await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
  cleanup();
  form({ group: { ...group, id: 'trip-1' } });
  expect(screen.getByRole('radio', { name: 'You' })).toBeChecked();
  expect(screen.getByText('3 of 3')).toBeInTheDocument();
  expect(screen.getByRole('radio', { name: 'Other' })).toBeChecked();
});

it('guesses the category from the description until you choose one', () => {
  form();
  fill('Cabin, 2 nights', '400');
  expect(screen.getByRole('radio', { name: 'Stay' })).toBeChecked();
  fill('Groceries for the cabin', '400');
  expect(screen.getByRole('radio', { name: 'Food' })).toBeChecked();
  fill('Souvenirs', '400');
  expect(screen.getByRole('radio', { name: 'Other' })).toBeChecked();
  fireEvent.click(screen.getByRole('radio', { name: 'Activities' }));
  fill('Gas', '40');
  expect(screen.getByRole('radio', { name: 'Activities' })).toBeChecked();
});

it('does not pop the keyboard when editing an existing expense', () => {
  const expense = { id: 'e1', description: 'Gas', amount_minor: 4000, paid_by: 'matt', split_mode: 'equal', date: '2026-10-20',
    category: 'transport', notes: '', shares: { matt: 2000, alex: 2000 } };
  form({ expense });
  expect(screen.getByLabelText('Amount (USD)')).not.toHaveFocus();
});

it('records several payers and a percentage split, sending percentages as basis points', async () => {
  const save = form();
  fill('Cabin', '300');
  fireEvent.click(screen.getByRole('radio', { name: 'Several people' }));
  fireEvent.change(screen.getByRole('textbox', { name: 'Matt paid (USD)' }), { target: { value: '200' } });
  fireEvent.change(screen.getByRole('textbox', { name: 'Alex paid (USD)' }), { target: { value: '50' } });
  expect(screen.getByText('$50.00 left to assign')).toBeInTheDocument();
  fireEvent.change(screen.getByRole('textbox', { name: 'Alex paid (USD)' }), { target: { value: '100' } });
  fireEvent.click(screen.getByRole('radio', { name: 'By percent' }));
  fireEvent.change(screen.getByRole('textbox', { name: 'Percent for Matt' }), { target: { value: '50' } });
  fireEvent.change(screen.getByRole('textbox', { name: 'Percent for Alex' }), { target: { value: '25' } });
  expect(screen.getByText('25% left to assign')).toBeInTheDocument();
  fireEvent.change(screen.getByRole('textbox', { name: 'Percent for Jamie' }), { target: { value: '25' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save expense' }));
  await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
  expect(save.mock.calls[0][0]).toMatchObject({ amount_minor: 30000, paid_by: 'matt', payers: { matt: 20000, alex: 10000 },
    split_mode: 'percent', shares: { matt: 5000, alex: 2500, jamie: 2500 } });
});

it('refuses to drop a payer amount it cannot read', async () => {
  const save = form();
  fill('Cabin', '100');
  fireEvent.click(screen.getByRole('radio', { name: 'Several people' }));
  fireEvent.change(screen.getByRole('textbox', { name: 'Matt paid (USD)' }), { target: { value: '10.001' } });
  fireEvent.change(screen.getByRole('textbox', { name: 'Alex paid (USD)' }), { target: { value: '70' } });
  fireEvent.change(screen.getByRole('textbox', { name: 'Jamie paid (USD)' }), { target: { value: '30' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save expense' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Check the amount Matt paid.');
  expect(save).not.toHaveBeenCalled();
});
