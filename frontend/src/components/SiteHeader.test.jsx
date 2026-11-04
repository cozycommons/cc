import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, useLocation, useNavigate } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import SiteHeader from './SiteHeader.jsx';

const identity = vi.hoisted(() => ({ current: null, signIn: vi.fn(), signOut: vi.fn() }));
vi.mock('./commonsIdentity.js', () => ({ useCommonsIdentity: () => identity.current,
  signInToCommons: identity.signIn, signOutOfCommons: identity.signOut }));
beforeEach(() => {
  identity.current = { status: 'signed-out', user: null, profile: null };
  identity.signIn.mockReset(); identity.signOut.mockReset();
});
const sam = { status: 'signed-in', user: { id: 'u1' },
  profile: { user_id: 'u1', display_name: 'Sam', email: 'sam@example.test', avatar_url: 'https://cdn.test/sam.webp' } };

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

describe('SiteHeader account', () => {
  it('shows the signed-in avatar on every page, with account and agent links', () => {
    identity.current = sam;
    render(<MemoryRouter><SiteHeader /></MemoryRouter>);
    const trigger = screen.getByRole('button', { name: 'Account: Sam' });
    expect(trigger.querySelector('img')).toHaveAttribute('src', 'https://cdn.test/sam.webp');
    fireEvent.click(trigger);
    const menu = screen.getByRole('navigation', { name: 'Account' });
    expect(menu).toHaveTextContent('sam@example.test');
    expect(screen.getByRole('link', { name: 'Your profile' })).toHaveAttribute('href', '/account');
    expect(screen.getByRole('link', { name: 'Connected agents' })).toHaveAttribute('href', '/account#agents');
    fireEvent.click(screen.getByRole('button', { name: 'Sign out' }));
    expect(identity.signOut).toHaveBeenCalled();
  });

  it('adds product links and closes on Escape', () => {
    identity.current = sam;
    const onSelect = vi.fn();
    render(<MemoryRouter><SiteHeader product="Dice" to="/dice" accountItems={[
      { label: 'Dice profile', to: '/dice/profile/u1' }, { label: 'Venmo', onSelect }]} /></MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: 'Account: Sam' }));
    expect(screen.getByRole('link', { name: 'Dice profile' })).toHaveAttribute('href', '/dice/profile/u1');
    fireEvent.click(screen.getByRole('button', { name: 'Venmo' }));
    expect(onSelect).toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Account: Sam' }));
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('navigation', { name: 'Account' })).not.toBeInTheDocument();
  });

  it('offers Google sign-in when signed out, a product sign-in instead, or none', () => {
    const { unmount } = render(<MemoryRouter><SiteHeader /></MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(identity.signIn).toHaveBeenCalled();
    unmount();
    const harness = vi.fn();
    const second = render(<MemoryRouter><SiteHeader onSignIn={harness} /></MemoryRouter>);
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(harness).toHaveBeenCalled();
    second.unmount();
    render(<MemoryRouter><SiteHeader onSignIn={null} /></MemoryRouter>);
    expect(screen.queryByRole('button', { name: 'Sign in' })).not.toBeInTheDocument();
  });
});
