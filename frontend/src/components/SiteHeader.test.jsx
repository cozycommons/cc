import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import SiteHeader from './SiteHeader.jsx';

function Where() {
  const location = useLocation();
  return <output>{`${location.pathname}${location.search}`}</output>;
}

function renderAt(entries, props = {}) {
  render(
    <MemoryRouter initialEntries={entries} initialIndex={entries.length - 1}>
      <SiteHeader product="Trips" to="/trips" {...props} />
      <Where />
    </MemoryRouter>,
  );
}

describe('SiteHeader back button', () => {
  it('appears by default below a product home, and not on the home itself', () => {
    renderAt(['/trips']);
    expect(screen.queryByRole('button', { name: 'Back' })).not.toBeInTheDocument();
  });

  it('steps back through in-app history', () => {
    renderAt(['/trips', '/trips/t1?tab=history']);
    fireEvent.click(screen.getByRole('button', { name: 'Back' }));
    expect(screen.getByText('/trips')).toBeInTheDocument();
  });

  it('goes to the product home when the page was opened directly', () => {
    renderAt(['/trips/t1']);
    fireEvent.click(screen.getByRole('button', { name: 'Back' }));
    expect(screen.getByText('/trips')).toBeInTheDocument();
  });

  it('uses a product-specific parent when one is given', () => {
    renderAt(['/trips/t1/expenses'], { backFallback: (pathname) => pathname.replace(/\/expenses$/, '') });
    fireEvent.click(screen.getByRole('button', { name: 'Back' }));
    expect(screen.getByText('/trips/t1')).toBeInTheDocument();
  });

  it('can be turned off', () => {
    renderAt(['/trips/t1'], { back: false });
    expect(screen.queryByRole('button', { name: 'Back' })).not.toBeInTheDocument();
  });

  it('is disabled while the product link is', () => {
    renderAt(['/trips/t1'], { productDisabled: true });
    expect(screen.getByRole('button', { name: 'Back' })).toBeDisabled();
  });

  it('never shows on the site home header, which has no product', () => {
    render(<MemoryRouter initialEntries={['/design']}><SiteHeader /></MemoryRouter>);
    expect(screen.queryByRole('button', { name: 'Back' })).not.toBeInTheDocument();
  });
});
