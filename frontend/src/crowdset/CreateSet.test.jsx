import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import CreateSet from './CreateSet';
import { matchesSearch } from './setDetails';

afterEach(cleanup);
const event = { id: 'event', name: 'Artist', artist: 'Artist', venue: 'Brooklyn', starts_at: '2026-10-20T03:00:00Z', ends_at: '2026-10-20T05:00:00Z', timezone: 'America/New_York' };
function fill() {
  for (const [label, value] of Object.entries({ Artist: ' Artist ', Venue: ' Brooklyn ', Start: '2026-10-19T23:00', End: '2026-10-20T01:00', 'Time zone': 'America/New_York' })) {
    const input = screen.getByLabelText(label);
    if (label === 'Start' || label === 'End') fireEvent.input(input, { target: { value } });
    else fireEvent.change(input, { target: { value } });
  }
  fireEvent.click(screen.getByRole('button', { name: 'Create set' }));
}

it('submits local event times and a time zone across midnight with the required legacy name', () => {
  const onCreate = vi.fn();
  render(<CreateSet sets={[]} structured onCreate={onCreate} />);
  fill();
  expect(onCreate).toHaveBeenCalledWith({ name: 'Artist', artist: 'Artist', venue: 'Brooklyn', starts_at: '2026-10-19T23:00', ends_at: '2026-10-20T01:00', timezone: 'America/New_York' });
});

it('surfaces a duplicate on the event’s local date before creating another set', () => {
  const onCreate = vi.fn();
  const onChoose = vi.fn();
  render(<CreateSet sets={[event]} structured onCreate={onCreate} onChoose={onChoose} />);
  fill();
  expect(onCreate).not.toHaveBeenCalled();
  expect(screen.getByRole('heading', { name: 'Possible duplicate' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: /Open set/ }));
  expect(onChoose).toHaveBeenCalledWith(event);
  fireEvent.click(screen.getByRole('button', { name: 'Create a different set' }));
  expect(onCreate).toHaveBeenCalledOnce();
});

it('rejects a range whose end equals its start', () => {
  const onCreate = vi.fn();
  render(<CreateSet sets={[]} structured onCreate={onCreate} />);
  fill();
  onCreate.mockClear();
  fireEvent.change(screen.getByLabelText('End'), { target: { value: '2026-10-19T23:00' } });
  fireEvent.click(screen.getByRole('button', { name: 'Create set' }));
  expect(screen.getByRole('alert')).toHaveTextContent('End must be after start.');
  expect(onCreate).not.toHaveBeenCalled();
});

it('searches artist, venue and the displayed local date together', () => {
  expect(matchesSearch(event, 'ARTIST brooklyn Oct 19')).toBe(true);
  expect(matchesSearch(event, 'another venue')).toBe(false);
  expect(matchesSearch({ name: 'Legacy set' }, 'legacy')).toBe(true);
});
