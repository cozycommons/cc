import React from 'react';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { BalancesPanel, VenmoReview } from './Settle.jsx';

const members = [{ id: 'me', name: 'Matt', venmo_username: 'matt-rivera' }, { id: 'a', name: 'Alex', venmo_username: 'alex-rivera' }, { id: 'b', name: 'Jamie', venmo_username: 'jamie-rivera' }];
const transfers = [{ from_member: 'a', to_member: 'me', amount_minor: 1234 }, { from_member: 'b', to_member: 'me', amount_minor: 5678 }];
const obligations = transfers.map((t, i) => ({ ...t, id: `o${i}`, reference: `CZ-00000${i}`, status: 'open', created_at: '2026-01-01T00:00:00+00:00', cycle: 0 }));
const group = { id: 'trip', name: 'Cabin', currency: 'USD', members, transfers, obligations, balances: { me: 6912, a: -1234, b: -5678 }, expenses: [], repayments: [], revision: 2 };
const request = vi.fn().mockResolvedValue({ found: false });
afterEach(() => { cleanup(); vi.clearAllMocks(); });

it('requests the exact debtor and amount from each row without mutating the ledger', async () => {
  const settle = vi.fn();
  render(<BalancesPanel group={group} me={members[0]} request={request} onSettle={settle} />);
  expect(screen.getByRole('list', { name: 'Payments' })).toBeInTheDocument();
  const first = screen.getByRole('link', { name: 'Request $12.34 from @alex-rivera' });
  expect(first).toHaveAttribute('href', 'https://venmo.com/alex-rivera?txn=charge&amount=12.34&note=Cozy%20Trips%20%C2%B7%20Cabin%20%C2%B7%20CZ-000000');
  expect(screen.getByRole('link', { name: 'Request $56.78 from @jamie-rivera' })).toHaveAttribute('href', 'https://venmo.com/jamie-rivera?txn=charge&amount=56.78&note=Cozy%20Trips%20%C2%B7%20Cabin%20%C2%B7%20CZ-000001');
  first.addEventListener('click', e => e.preventDefault());
  fireEvent.click(first);
  expect(settle).not.toHaveBeenCalled();
  fireEvent.focus(window);
  expect(await screen.findByText('Got $12.34 from Alex?')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Not yet' }));
  expect(settle).not.toHaveBeenCalled();
  expect(screen.queryByText('Got $12.34 from Alex?')).not.toBeInTheDocument();
  fireEvent.click(first); fireEvent.focus(window);
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Got it' })));
  expect(settle).toHaveBeenCalledTimes(1);
  expect(settle.mock.calls[0][0]).toMatchObject(obligations[0]);
});

it('leaves a payer obligation open after Not yet and navigation away', async () => {
  const label = 'Not yet';
  const settle = vi.fn(), record = vi.fn();
  const view = render(<VenmoReview group={group} transfer={transfers[0]} role="pay" obligation={obligations[0]} request={request} onSettle={settle} onRecord={record} />);
  const link = screen.getByRole('link', { name: 'Pay $12.34 in Venmo' });
  expect(screen.getByText('Cozy Trips · Cabin · CZ-000000')).toBeInTheDocument();
  expect(link).toHaveAttribute('href', 'https://venmo.com/matt-rivera?txn=pay&amount=12.34&note=Cozy%20Trips%20%C2%B7%20Cabin%20%C2%B7%20CZ-000000');
  link.addEventListener('click', e => e.preventDefault());
  fireEvent.click(link); fireEvent.focus(window);
  expect(screen.getByText('Sent $12.34 to Matt?')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: label }));
  view.unmount(); fireEvent.focus(window);
  expect(settle).not.toHaveBeenCalled(); expect(record).not.toHaveBeenCalled();
});

it('settles only on Sent, and uses the exact profile link for checking', async () => {
  const settle = vi.fn().mockResolvedValue({});
  render(<VenmoReview group={group} transfer={transfers[0]} role="pay" obligation={obligations[0]} request={request} onSettle={settle} />);
  expect(screen.getByRole('link', { name: 'Check in Venmo' })).toHaveAttribute('href', 'https://venmo.com/u/matt-rivera');
  expect(screen.getByRole('link', { name: 'Check in Venmo' })).toHaveClass('cc-button--ghost');
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Sent' })));
  expect(settle).toHaveBeenCalledExactlyOnceWith(obligations[0]);
});

it('offers nudge only after three days and hides it for 48 hours after nudging', () => {
  const nudge = vi.fn();
  const view = render(<BalancesPanel group={group} me={members[0]} request={request} onNudge={nudge} />);
  fireEvent.click(screen.getAllByRole('button', { name: 'Nudge' })[0]);
  expect(nudge).toHaveBeenCalledWith(obligations[0]);
  view.rerender(<BalancesPanel group={{ ...group, obligations: obligations.map(o => ({ ...o, nudged_at: new Date().toISOString() })) }} me={members[0]} request={request} onNudge={nudge} />);
  expect(screen.queryByRole('button', { name: 'Nudge' })).not.toBeInTheDocument();
});

it('offers Undo from a settled row', () => {
  const undo = vi.fn();
  const settled = { ...obligations[0], status: 'settled', cycle: 2 };
  render(<BalancesPanel group={{ ...group, obligations: [settled], transfers: [], repayments: [{ ...transfers[0], id: settled.id, date: '2026-10-25' }] }} me={members[0]} request={request} onUndo={undo} />);
  fireEvent.click(screen.getByRole('button', { name: /Undo payment from/ }));
  expect(undo).toHaveBeenCalledWith(settled);
});

it.each(['amount', 'id', 'cycle', 'handle'])('drops the request return prompt when its %s changes', async field => {
  const settle = vi.fn();
  const view = render(<BalancesPanel group={group} me={members[0]} request={request} onSettle={settle} />);
  const link = screen.getByRole('link', { name: 'Request $12.34 from @alex-rivera' });
  link.addEventListener('click', e => e.preventDefault()); fireEvent.click(link); fireEvent.focus(window);
  expect(screen.getByRole('button', { name: 'Got it' })).toBeInTheDocument();
  const changed = { ...obligations[0], ...(field === 'amount' ? { amount_minor: 5678 } : field === 'id' ? { id: 'replacement' } : field === 'cycle' ? { cycle: 1 } : {}) };
  const refreshed = { ...group, obligations: [changed, obligations[1]], transfers: [changed, transfers[1]], members: members.map(m => m.id === 'a' && field === 'handle' ? { ...m, venmo_username: 'different-handle' } : m) };
  view.rerender(<BalancesPanel group={refreshed} me={members[0]} request={request} onSettle={settle} />);
  fireEvent.focus(window);
  expect(screen.queryByRole('button', { name: 'Got it' })).not.toBeInTheDocument();
  expect(settle).not.toHaveBeenCalled();
});

it('records the opened Pay amount after the current pair changes', async () => {
  const settle = vi.fn();
  const view = render(<VenmoReview group={group} transfer={transfers[0]} role="pay" obligation={obligations[0]} request={request} onSettle={settle} />);
  const link = screen.getByRole('link', { name: 'Pay $12.34 in Venmo' });
  link.addEventListener('click', e => e.preventDefault()); fireEvent.click(link);
  const changed = { ...obligations[0], id: 'new', amount_minor: 5678 };
  const refreshed = { ...group, obligations: [{ ...obligations[0], status: 'replaced' }, changed] };
  view.rerender(<VenmoReview group={refreshed} transfer={changed} role="pay" obligation={changed} request={request} onSettle={settle} />);
  fireEvent.focus(window);
  expect(screen.getByText('Amounts changed.')).toBeInTheDocument();
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Sent' })));
  expect(settle).toHaveBeenCalledTimes(1);
  expect(settle.mock.calls[0][0]).toMatchObject({ id: 'o0', amount_minor: 1234, cycle: 0 });
});

it.each([true, false])('shows a Pay sheet checkmark only for a confirmed payee: %s', async confirmed => {
  const payGroup = { ...group, members: members.map(m => m.id === 'me' ? { ...m, venmo_confirmed: confirmed } : m) };
  render(<VenmoReview group={payGroup} transfer={transfers[0]} role="pay" obligation={obligations[0]} request={request} />);
  expect(Boolean(screen.queryByRole('img', { name: 'Confirmed Venmo' }))).toBe(confirmed);
});

it('shows confirmed badges in the payments table and the person menu', async () => {
  const { PersonSheet } = await import('./People.jsx');
  const confirmedMembers = members.map(m => ({ ...m, venmo_confirmed: m.id === 'a' }));
  const view = render(<BalancesPanel group={{ ...group, members: confirmedMembers }} me={members[0]} request={request} />);
  expect(screen.getAllByRole('img', { name: 'Confirmed Venmo' })).toHaveLength(1);
  view.unmount();
  render(<PersonSheet group={group} member={confirmedMembers[1]} request={request} />);
  expect(screen.getByRole('img', { name: 'Confirmed Venmo' })).toBeInTheDocument();
});

it('keeps a Request prompt when its row disappears and records the original debt', async () => {
  const settle = vi.fn();
  const view = render(<BalancesPanel group={group} me={members[0]} request={request} onSettle={settle} />);
  const link = screen.getByRole('link', { name: 'Request $12.34 from @alex-rivera' });
  link.addEventListener('click', e => e.preventDefault()); fireEvent.click(link);
  const refreshed = { ...group, transfers: [transfers[1]], obligations: [{ ...obligations[0], status: 'replaced' }, obligations[1]] };
  view.rerender(<BalancesPanel group={refreshed} me={members[0]} request={request} onSettle={settle} />);
  fireEvent.focus(window);
  expect(screen.getByText('Got $12.34 from Alex?')).toBeInTheDocument();
  expect(screen.getByText('Amounts changed.')).toBeInTheDocument();
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Got it' })));
  expect(settle.mock.calls[0][0]).toMatchObject({ id: 'o0', cycle: 0, amount_minor: 1234 });
});

it('follows the current pair amount before opening and shows Close if the pair is gone', () => {
  const updated = { ...obligations[0], amount_minor: 4500, id: 'new' };
  const view = render(<VenmoReview group={{ ...group, obligations: [updated] }} transfer={transfers[0]} obligation={updated} role="pay" request={request} />);
  expect(screen.getByRole('link', { name: 'Pay $45.00 in Venmo' })).toHaveAttribute('href', expect.stringContaining('amount=45.00'));
  view.rerender(<VenmoReview group={{ ...group, obligations: [] }} transfer={transfers[0]} role="pay" request={request} />);
  expect(screen.getByText('This payment changed.')).toBeInTheDocument();
  expect(screen.getAllByRole('button')).toHaveLength(1);
  expect(screen.getByRole('button', { name: 'Close' })).toBeInTheDocument();
});

it('keeps another pair\'s opened payment out of this Pay sheet', async () => {
  const settle = vi.fn().mockResolvedValue({});
  const payGroup = { ...group, transfers: [{ from_member: 'a', to_member: 'me', amount_minor: 1234 }, { from_member: 'a', to_member: 'b', amount_minor: 4500 }] };
  const toJamie = { ...payGroup.transfers[1], id: 'o9', reference: 'CZ-000009', status: 'open', created_at: '2026-01-01T00:00:00+00:00', cycle: 0 };
  const withJamie = { ...payGroup, obligations: [obligations[0], toJamie] };
  const flow = { opened: { ...obligations[0], role: 'pay', handle: 'matt-rivera' }, pending: { ...obligations[0], role: 'pay', handle: 'matt-rivera' }, returned: true, item: obligations[0], open: vi.fn(), dismiss: vi.fn() };
  render(<VenmoReview group={withJamie} transfer={payGroup.transfers[1]} role="pay" obligation={toJamie} request={request} onSettle={settle} paymentFlow={flow} />);
  const link = screen.getByRole('link', { name: 'Pay $45.00 in Venmo' });
  expect(link).toHaveAttribute('href', 'https://venmo.com/jamie-rivera?txn=pay&amount=45.00&note=Cozy%20Trips%20%C2%B7%20Cabin%20%C2%B7%20CZ-000009');
  expect(screen.queryByText('Sent $12.34 to Matt?')).not.toBeInTheDocument();
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Sent' })));
  expect(settle).toHaveBeenCalledExactlyOnceWith(toJamie);
});
