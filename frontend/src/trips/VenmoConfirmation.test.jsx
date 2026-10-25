import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import VenmoConfirmation from './VenmoConfirmation.jsx';

afterEach(cleanup);

it('links the public profile and confirms the displayed handle with a primary action', async () => {
  const confirm = vi.fn().mockResolvedValue({});
  render(<VenmoConfirmation username="Jayce-e" onConfirm={confirm} onCancel={vi.fn()} />);
  const profile = screen.getByRole('link', { name: '@Jayce-e on Venmo' });
  expect(profile).toHaveAttribute('href', 'https://venmo.com/u/Jayce-e');
  expect(profile).toHaveAttribute('target', '_blank');
  expect(profile).toHaveAttribute('rel', 'noopener noreferrer');
  const button = screen.getByRole('button', { name: "Yes, that's me" });
  expect(button).toHaveClass('cc-button--primary');
  fireEvent.click(button);
  await waitFor(() => expect(confirm).toHaveBeenCalledWith('Jayce-e'));
});

it('previews a corrected profile before saving and keeps the draft after a failed save', async () => {
  const confirm = vi.fn().mockRejectedValueOnce(new Error('Connection lost')).mockResolvedValue({});
  render(<VenmoConfirmation username="old-handle" onConfirm={confirm} onCancel={vi.fn()} />);
  fireEvent.click(screen.getByRole('button', { name: 'Change handle' }));
  fireEvent.change(screen.getByLabelText('Your Venmo username'), { target: { value: '@correct-handle' } });
  expect(screen.getByRole('link', { name: '@correct-handle on Venmo' })).toHaveAttribute('href', 'https://venmo.com/u/correct-handle');
  fireEvent.click(screen.getByRole('button', { name: "Yes, that's me" }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Connection lost');
  expect(screen.getByLabelText('Your Venmo username')).toHaveValue('@correct-handle');
  fireEvent.click(screen.getByRole('button', { name: "Yes, that's me" }));
  await waitFor(() => expect(confirm).toHaveBeenCalledTimes(2));
  expect(confirm).toHaveBeenLastCalledWith('correct-handle');
});

it('asks for a missing handle and rejects blank or malformed usernames without saving', async () => {
  const confirm = vi.fn();
  render(<VenmoConfirmation username={null} onConfirm={confirm} onCancel={vi.fn()} />);
  expect(screen.getByLabelText('Your Venmo username')).toHaveValue('');
  fireEvent.click(screen.getByRole('button', { name: "Yes, that's me" }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Enter your Venmo username.');
  fireEvent.change(screen.getByLabelText('Your Venmo username'), { target: { value: 'bad handle' } });
  fireEvent.click(screen.getByRole('button', { name: "Yes, that's me" }));
  expect(await screen.findByRole('alert')).toHaveTextContent('5–30 letters');
  expect(screen.queryByRole('link')).not.toBeInTheDocument();
  expect(confirm).not.toHaveBeenCalled();
});

it('does not record confirmation when cancelled', () => {
  const confirm = vi.fn(), cancel = vi.fn();
  render(<VenmoConfirmation username="test-handle" onConfirm={confirm} onCancel={cancel} />);
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  expect(cancel).toHaveBeenCalledTimes(1);
  expect(confirm).not.toHaveBeenCalled();
});
