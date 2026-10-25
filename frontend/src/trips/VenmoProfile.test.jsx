import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import VenmoConfirmation from './VenmoConfirmation.jsx';
import VenmoProfile from './VenmoProfile.jsx';

afterEach(cleanup);
const profile = { found: true, displayName: 'Alex Rivera', initials: 'AR', photoUrl: 'https://pics-v3.venmo.com/a.jpg', active: true };
it('shows loading then name and photo, with initials if the photo fails', async () => {
  const request = vi.fn().mockResolvedValue(profile);
  const { container } = render(<VenmoProfile handle="alex-rivera" request={request} />);
  expect(screen.getByRole('status')).toHaveTextContent('Finding');
  expect(await screen.findByText('Alex Rivera')).toBeInTheDocument();
  expect(screen.getByRole('link')).toHaveAttribute('href', 'https://venmo.com/u/alex-rivera');
  fireEvent.error(container.querySelector('img'));
  expect(screen.getByText('AR')).toBeInTheDocument();
});
it.each([{ found: false }, { ...profile, active: false }])('keeps a friendly fallback for missing or inactive profiles', async result => {
  render(<VenmoProfile handle="alex-rivera" request={vi.fn().mockResolvedValue(result)} />);
  await waitFor(() => expect(screen.getByRole('status')).not.toHaveTextContent('Finding'));
  expect(screen.getByRole('status').textContent).toMatch(/Preview unavailable|isn’t active/);
  expect(screen.getByRole('link')).toBeInTheDocument();
});
it('debounces edits and saves the normalized handle', async () => {
  const request = vi.fn().mockResolvedValue(profile);
  const save = vi.fn();
  render(<VenmoConfirmation username="alex-rivera" request={request} onConfirm={save} onCancel={() => {}} />);
  fireEvent.click(screen.getByRole('button', { name: 'Change handle' }));
  fireEvent.change(screen.getByLabelText('Your Venmo username'), { target: { value: '@jamie-rivera' } });
  expect(request).not.toHaveBeenCalled();
  await waitFor(() => expect(request).toHaveBeenCalledWith('/venmo/profile?handle=jamie-rivera'));
  fireEvent.click(screen.getByRole('button', { name: "Save handle" }));
  await waitFor(() => expect(save).toHaveBeenCalledWith('jamie-rivera'));
});
it('ignores stale responses after a handle change', async () => {
  let resolve;
  const request = vi.fn().mockImplementationOnce(() => new Promise(r => { resolve = r; })).mockResolvedValue({ found: false });
  const view = render(<VenmoProfile handle="alex-rivera" request={request} />);
  await waitFor(() => expect(request).toHaveBeenCalled());
  view.rerender(<VenmoProfile handle="jamie-rivera" request={request} />);
  await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Preview unavailable'));
  resolve(profile);
  await waitFor(() => expect(screen.queryByText('Alex Rivera')).not.toBeInTheDocument());
});

it('does not request a missing handle', async () => {
  const request = vi.fn();
  const { container } = render(<VenmoProfile handle={null} request={request} />);
  await new Promise(resolve => setTimeout(resolve, 20));
  expect(request).not.toHaveBeenCalled();
  expect(container).toBeEmptyDOMElement();
});
