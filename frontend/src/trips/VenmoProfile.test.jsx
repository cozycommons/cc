import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import VenmoConfirmation from './VenmoConfirmation.jsx';
import VenmoProfile from './VenmoProfile.jsx';

afterEach(cleanup);
const profile = { found: true, displayName: 'Alex Rivera', initials: 'AR', photoUrl: '/venmo/photo?handle=alex-rivera&sig=synthetic', active: true };
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
  expect(screen.getByRole('status').textContent).toBe(result.found ? 'Inactive profile' : '');
  expect(screen.getByRole('link')).toBeInTheDocument();
});
it('debounces edits and saves the normalized handle', async () => {
  const request = vi.fn().mockResolvedValue(profile);
  const save = vi.fn();
  render(<VenmoConfirmation username="alex-rivera" request={request} onConfirm={save} onCancel={() => {}} />);
  fireEvent.click(screen.getByRole('button', { name: "No, it's not" }));
  fireEvent.change(screen.getByLabelText('Your Venmo username'), { target: { value: '@jamie-rivera' } });
  expect(request).not.toHaveBeenCalled();
  await waitFor(() => expect(request).toHaveBeenCalledWith('/venmo/profile?handle=jamie-rivera'));
  fireEvent.click(screen.getByRole('button', { name: 'Review handle' }));
  expect(save).not.toHaveBeenCalled();
  fireEvent.click(await screen.findByRole('button', { name: "Yes, that's me" }));
  await waitFor(() => expect(save).toHaveBeenCalledWith('jamie-rivera'));
});
it('ignores stale responses after a handle change', async () => {
  let resolve;
  const request = vi.fn().mockImplementationOnce(() => new Promise(r => { resolve = r; })).mockResolvedValue({ found: false });
  const view = render(<VenmoProfile handle="alex-rivera" request={request} />);
  await waitFor(() => expect(request).toHaveBeenCalled());
  view.rerender(<VenmoProfile handle="jamie-rivera" request={request} />);
  await waitFor(() => expect(screen.getByRole('status')).not.toHaveTextContent('Finding'));
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

it('labels a confirmed card and explains who confirmed it on tap, hover and keyboard focus', async () => {
  render(<VenmoProfile handle="alex-rivera" confirmed request={vi.fn().mockResolvedValue(profile)} />);
  await screen.findByText('Alex Rivera');
  expect(screen.getByText('Confirmed Venmo')).toBeInTheDocument();
  expect(screen.getByText('Confirmed Venmo').querySelector('svg')).toBeNull();
  expect(document.querySelectorAll('.trips-venmo-confirmed')).toHaveLength(1);
  const badge = screen.getByRole('button', { name: 'About confirmed Venmo' });
  expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  fireEvent.click(badge);
  expect(screen.getByRole('tooltip')).toHaveTextContent('Alex confirmed this is their Venmo.');
  fireEvent.keyDown(badge, { key: 'Escape' });
  expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  fireEvent.mouseEnter(badge.parentElement);
  expect(screen.getByRole('tooltip')).toBeInTheDocument();
  fireEvent.mouseLeave(badge.parentElement);
  expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  fireEvent.focus(badge);
  expect(screen.getByRole('tooltip')).toBeInTheDocument();
  fireEvent.blur(badge);
  expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
});

it('shows initials right away and keeps them under the photo until it loads', async () => {
  const request = vi.fn().mockResolvedValue({ found: true, handle: 'alex-rivera', displayName: 'Alex Rivera', initials: 'AR', photoUrl: '/venmo/photo?handle=alex-rivera&v=1' });
  const { container } = render(<VenmoProfile handle="alex-rivera" request={request} />);
  expect(container.querySelector('.trips-venmo-avatar')).toHaveTextContent('A');
  const img = await waitFor(() => { const el = container.querySelector('.trips-venmo-avatar img'); if (!el) throw new Error('no img'); return el; });
  expect(container.querySelector('.trips-venmo-avatar')).toHaveTextContent('AR');
  expect(img).not.toHaveClass('is-loaded');
  fireEvent.load(img);
  expect(img).toHaveClass('is-loaded');
});
