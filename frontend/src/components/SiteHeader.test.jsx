import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';
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

  it('shows on a page below the product home', () => {
    renderAt(['/trips/t1']);
    expect(screen.getByRole('button', { name: 'Back' })).toBeInTheDocument();
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

describe('SiteHeader back button after an in-page anchor', () => {
  it('still steps back when the current entry has no router state', () => {
    function Harness() {
      const navigate = useNavigate();
      return <button type="button" onClick={() => navigate('/trips/t1?tab=expenses')}>open expenses</button>;
    }
    render(
      <MemoryRouter initialEntries={['/trips/t1']}>
        <SiteHeader product="Trips" to="/trips" />
        <Harness />
        <Where />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByText('open expenses'));
    fireEvent.click(screen.getByRole('button', { name: 'Back' }));
    expect(screen.getByText('/trips/t1')).toBeInTheDocument();
  });
});
