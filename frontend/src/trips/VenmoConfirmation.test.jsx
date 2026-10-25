import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import VenmoConfirmation from './VenmoConfirmation.jsx';

const request = vi.fn(async path => ({ found: true, displayName: path.includes('correct-handle') ? 'Correct Person' : 'Alex Rivera', photoUrl: '/venmo/photo?handle=synthetic', initials: 'AR' }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });
const yes = async () => { const button = await screen.findByRole('button', { name: "Yes, that's me" }); await waitFor(() => expect(button).toBeEnabled()); fireEvent.click(button); };

it('only Yes confirms the displayed card and shows an accessible blue checkmark', async () => {
  const confirm = vi.fn().mockResolvedValue({});
  render(<VenmoConfirmation username="alex-rivera" request={request} onConfirm={confirm} onCancel={vi.fn()} />);
  expect(await screen.findByText('Alex Rivera')).toBeInTheDocument();
  expect(screen.getByText('@alex-rivera')).toBeInTheDocument();
  expect(screen.queryByRole('img', { name: 'Confirmed Venmo' })).not.toBeInTheDocument();
  expect(screen.queryByText('Confirmed Venmo')).not.toBeInTheDocument();
  await yes();
  await waitFor(() => expect(confirm).toHaveBeenCalledExactlyOnceWith('alex-rivera'));
  expect(await screen.findByRole('img', { name: 'Confirmed Venmo' })).toBeInTheDocument();
  expect(screen.queryByText('Is this you?')).not.toBeInTheDocument();
});

it('shows no badge on the question card even for a previously confirmed handle', async () => {
  render(<VenmoConfirmation username="alex-rivera" confirmed request={request} onConfirm={vi.fn()} />);
  expect(await screen.findByText('Alex Rivera')).toBeInTheDocument();
  expect(screen.getByText('Is this you?')).toBeInTheDocument();
  expect(screen.queryByRole('img', { name: 'Confirmed Venmo' })).not.toBeInTheDocument();
  expect(screen.queryByText('Confirmed Venmo')).not.toBeInTheDocument();
});

it('No edits without confirming, updates the preview, and asks again before saving the new handle', async () => {
  const confirm = vi.fn().mockResolvedValue({});
  render(<VenmoConfirmation username="old-handle" confirmed request={request} onConfirm={confirm} />);
  expect(screen.getByText('Is this you?')).toBeInTheDocument();
  expect(screen.queryByRole('img', { name: 'Confirmed Venmo' })).not.toBeInTheDocument();
  expect(screen.queryByText('Confirmed Venmo')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: "No, it's not" }));
  expect(confirm).not.toHaveBeenCalled();
  expect(screen.queryByRole('img', { name: 'Confirmed Venmo' })).not.toBeInTheDocument();
  expect(screen.queryByText('Confirmed Venmo')).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText('Your Venmo username'), { target: { value: '@correct-handle' } });
  expect(await screen.findByText('Correct Person')).toBeInTheDocument();
  expect(screen.getByText('@correct-handle')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Review handle' }));
  expect(await screen.findByText('Is this you?')).toBeInTheDocument();
  expect(confirm).not.toHaveBeenCalled();
  expect(screen.queryByRole('img', { name: 'Confirmed Venmo' })).not.toBeInTheDocument();
  expect(screen.queryByText('Confirmed Venmo')).not.toBeInTheDocument();
  await yes();
  await waitFor(() => expect(confirm).toHaveBeenCalledExactlyOnceWith('correct-handle'));
  expect(await screen.findByRole('img', { name: 'Confirmed Venmo' })).toBeInTheDocument();
});

it('does not confirm a stale card while the new preview is pending', async () => {
  let resolve;
  const slow = vi.fn().mockImplementation(() => new Promise(r => { resolve = r; }));
  const confirm = vi.fn();
  render(<VenmoConfirmation username={null} request={slow} onConfirm={confirm} />);
  fireEvent.change(screen.getByLabelText('Your Venmo username'), { target: { value: 'new-handle' } });
  fireEvent.click(screen.getByRole('button', { name: 'Review handle' }));
  const button = await screen.findByRole('button', { name: "Yes, that's me" });
  expect(button).toBeDisabled(); fireEvent.click(button); expect(confirm).not.toHaveBeenCalled();
  await waitFor(() => expect(slow).toHaveBeenCalled());
  resolve({ found: false });
  await waitFor(() => expect(button).toBeEnabled());
  fireEvent.click(button); await waitFor(() => expect(confirm).toHaveBeenCalledWith('new-handle'));
});

it('keeps a failed Yes unconfirmed and supports retry', async () => {
  const confirm = vi.fn().mockRejectedValueOnce(new Error('Connection lost')).mockResolvedValue({});
  render(<VenmoConfirmation username="alex-rivera" request={request} onConfirm={confirm} />);
  await yes();
  expect(await screen.findByRole('alert')).toHaveTextContent('Connection lost');
  expect(screen.queryByRole('img', { name: 'Confirmed Venmo' })).not.toBeInTheDocument();
  expect(screen.queryByText('Confirmed Venmo')).not.toBeInTheDocument();
  await yes(); expect(await screen.findByRole('img', { name: 'Confirmed Venmo' })).toBeInTheDocument();
});

it('rejects blank or malformed handles without confirming', async () => {
  const confirm = vi.fn();
  render(<VenmoConfirmation username={null} request={request} onConfirm={confirm} />);
  fireEvent.click(screen.getByRole('button', { name: 'Review handle' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Enter your Venmo username.');
  fireEvent.change(screen.getByLabelText('Your Venmo username'), { target: { value: 'bad handle' } });
  fireEvent.click(screen.getByRole('button', { name: 'Review handle' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('5–30 letters'); expect(confirm).not.toHaveBeenCalled();
});
