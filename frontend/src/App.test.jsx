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

describe('top-level routes', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/');
  });

  afterEach(cleanup);

  it('leaves the home page empty', () => {
    const { container } = render(<App />);

    expect(container).toBeEmptyDOMElement();
  });

  it('serves Dice and initializes Supabase under /dice', () => {
    window.history.replaceState({}, '', '/dice/profile/player-id');

    render(<App />);

    expect(screen.getByText('Dice application')).toBeInTheDocument();
    expect(screen.getByTestId('supabase-provider')).toBeInTheDocument();
  });
});
