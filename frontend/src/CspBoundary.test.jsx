import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Link } from 'react-router-dom';
import { expect, it, vi } from 'vitest';
import CspBoundary from './CspBoundary.jsx';

it.each([['/', '/account#beli'], ['/account', '/dice'], ['/', '/%61ccount'], ['/', '/OAUTH/CONSENT']])('reloads before rendering across %s to %s', async (from, to) => {
  window.history.replaceState({}, '', from);
  const reload = vi.fn();
  render(<MemoryRouter initialEntries={[from]}><CspBoundary reload={reload}><Link to={to}>Navigate</Link></CspBoundary></MemoryRouter>);
  fireEvent.click(screen.getByText('Navigate'));
  await waitFor(() => expect(reload).toHaveBeenCalled());
  expect(screen.queryByText('Navigate')).toBeNull();
});
