import React from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App.jsx';

vi.mock('./contexts/SupabaseContext.jsx', () => ({
  SupabaseProvider: ({ children }) => <div data-testid="supabase-provider">{children}</div>,
}));

vi.mock('./dice/App.jsx', () => ({
  default: () => <div>Dice application</div>,
}));

vi.mock('./commons/CommonsScenePage.jsx', () => ({
  default: () => <div>Commons scene page</div>,
}));

vi.mock('../../design/dice/App.jsx', () => ({
  default: () => <div>Dice design system</div>,
}));

vi.mock('./crowdset/Crowdset.jsx', () => ({ default: () => <div>Crowdset application</div> }));

describe('top-level routes', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/');
  });

  afterEach(cleanup);

  it('serves the Wabi project picker home page with a Dice project card', () => {
    const { container } = render(<App />);

    expect(container).not.toBeEmptyDOMElement();
    expect(screen.getByRole('main')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'The shelf' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open Dice beer die records and stats' })).toHaveAttribute('href', '/dice');
    expect(screen.queryByText('Commons scene page')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open Crowdset concert videos' })).toHaveAttribute('href', '/crowdset');
  });

  it('serves Crowdset at its canonical URL', async () => {
    window.history.replaceState({}, '', '/crowdset');
    render(<App />);
    expect(await screen.findByText('Crowdset application')).toBeInTheDocument();
  });

  it('serves dedicated Crowdset watch links', async () => {
    window.history.replaceState({}, '', '/crowdset/isoknock-niteharts-2026');
    render(<App />);
    expect(await screen.findByText('Crowdset application')).toBeInTheDocument();
    expect(window.location.pathname).toBe('/crowdset/isoknock-niteharts-2026');
  });

  it('redirects old Crowdset links while preserving query and recording anchor', async () => {
    window.history.replaceState({}, '', '/crowd-set?view=set#recording-123');
    render(<App />);
    expect(await screen.findByText('Crowdset application')).toBeInTheDocument();
    expect(window.location.pathname + window.location.search + window.location.hash).toBe('/crowdset?view=set#recording-123');
  });

  it('serves the shared room at /scene', () => {
    window.history.replaceState({}, '', '/scene');

    render(<App />);

    expect(screen.getByText('Commons scene page')).toBeInTheDocument();
  });

  it('serves Dice and initializes Supabase under /dice', () => {
    window.history.replaceState({}, '', '/dice/profile/player-id');

    render(<App />);

    expect(screen.getByText('Dice application')).toBeInTheDocument();
    expect(screen.getByTestId('supabase-provider')).toBeInTheDocument();
  });

  it('serves the chosen Wabi component library at /design', async () => {
    window.history.replaceState({}, '', '/design');

    render(<App />);

    await waitFor(() => expect(screen.getByRole('heading', { name: /A small kit.*close at hand\./ })).toBeInTheDocument());
    expect(screen.getByRole('link', { name: 'landing room' })).toHaveAttribute('href', '/');
    expect(screen.getByRole('heading', { name: /Raised keys.*soft landing\./ })).toBeInTheDocument();
  });

  it('serves the Dice design system at /design/dice', async () => {
    window.history.replaceState({}, '', '/design/dice');

    render(<App />);

    await waitFor(() => expect(screen.getByText('Dice design system')).toBeInTheDocument());
  });
});
