import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
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

describe('top-level routes', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/');
  });

  afterEach(cleanup);

  it('serves a simple home page with a Dice project card', () => {
    const { container } = render(<App />);

    expect(container).not.toBeEmptyDOMElement();
    expect(screen.getByRole('main')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'A small room for things we make.' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Dice/ })).toHaveAttribute('href', '/dice');
    expect(screen.queryByText('Commons scene page')).not.toBeInTheDocument();
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
});
