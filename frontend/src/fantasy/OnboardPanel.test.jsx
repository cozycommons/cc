import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import OnboardPanel from './OnboardPanel.jsx';

const json = (status, body) => ({ status, ok: status < 400, json: async () => body });

function stubFetch(handler) {
  const calls = [];
  vi.stubGlobal('fetch', vi.fn(async (url, options = {}) => {
    const payload = JSON.parse(options.body || '{}');
    calls.push([url, payload]);
    return handler(payload, calls.length);
  }));
  return calls;
}

function fillAndSubmit() {
  fireEvent.change(screen.getByLabelText('ESPN email'), { target: { value: 'a@example.com' } });
  fireEvent.change(screen.getByLabelText('ESPN password'), { target: { value: 'pw-123' } });
  fireEvent.click(screen.getByRole('button', { name: 'Connect ESPN' }));
}

describe('login onboarding panel', () => {
  afterEach(() => { vi.unstubAllGlobals(); });

  it('connects, then shows the league/team echo and the one-time token', async () => {
    const calls = stubFetch(() => json(200, {
      id: 'acc-9', label: 'a', league_id: 1709148631, season: 2027,
      token: 'cce_test-token', lineup_automation_enabled: true,
      league_name: 'My 2027 League', team_name: 'mr diddles', team_id: 1,
    }));
    render(<OnboardPanel apiUrl="https://api.example.test" />);
    expect(screen.getByText(/never store your ESPN password/)).toBeTruthy();
    expect(screen.getByText(/cannot add, drop, or trade/)).toBeTruthy();
    fillAndSubmit();
    expect((await screen.findByText(/You’re connected/)).textContent).toContain('mr diddles');
    expect(screen.getByText(/Daily lineup setting is on/)).toBeTruthy();
    expect(screen.getByLabelText(/only time it’s shown/)).toHaveProperty('value', 'cce_test-token');
    expect(calls[0][0]).toBe('https://api.example.test/espn/onboard/login');
    expect(calls[0][1]).toMatchObject({ email: 'a@example.com', password: 'pw-123', enable_automation: true });
  });

  it('offers a league picker when the account has several leagues', async () => {
    const calls = stubFetch((payload, n) => (n === 1
      ? json(200, {
        status: 'league_selection_required', season: 2027,
        leagues: [
          { league_id: 111, name: 'League One', team_name: 'A Team' },
          { league_id: 222, name: 'League Two', team_name: 'B Team' },
        ],
      })
      : json(200, {
        id: 'acc-2', token: 'cce_second', lineup_automation_enabled: false,
        league_name: 'League Two', team_name: 'B Team',
      })));
    render(<OnboardPanel apiUrl="https://api.example.test" />);
    fillAndSubmit();
    expect(await screen.findByText(/more than one basketball league/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText('League'), { target: { value: '222' } });
    fireEvent.click(screen.getByRole('button', { name: 'Connect this league' }));
    expect(await screen.findByText(/You’re connected/)).toBeTruthy();
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls[1][1]).toMatchObject({ league_id: 222, email: 'a@example.com' });
  });

  it('explains the cookie fallback when ESPN demands verification', async () => {
    stubFetch(() => json(403, { detail: 'challenge_required' }));
    render(<OnboardPanel apiUrl="https://api.example.test" />);
    fillAndSubmit();
    expect((await screen.findByRole('alert')).textContent).toMatch(/cookie sign-up/);
  });

  it('reports a bad password plainly', async () => {
    stubFetch(() => json(401, { detail: 'invalid_credentials' }));
    render(<OnboardPanel apiUrl="https://api.example.test" />);
    fillAndSubmit();
    expect((await screen.findByRole('alert')).textContent).toMatch(/didn’t accept that email and password/);
  });

  it('renders nothing without an API URL', () => {
    const { container } = render(<OnboardPanel apiUrl={null} />);
    expect(container.firstChild).toBeNull();
  });
});
