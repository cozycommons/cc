import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import Fantasy from './Fantasy.jsx';
import { SNAPSHOT_V2 } from './fixture.js';

vi.mock('../api.js', () => ({ getUrl: () => 'https://api.example.test' }));
const session = { access_token: 'token-1' };
vi.mock('../supabase', () => ({ auth: { getSession: vi.fn(async () => globalThis.__session), signInWithGoogle: vi.fn() } }));

const json = (status, body) => ({ status, ok: status < 400, json: async () => body });

function server({ owners = [], suggestion, claim = body => json(200, body) }) {
  const calls = [];
  vi.stubGlobal('fetch', vi.fn(async (url, options = {}) => {
    calls.push([url, options.method || 'GET']);
    if (url.endsWith('/espn/public/predictions/latest')) return json(200, structuredClone(SNAPSHOT_V2));
    if (url.includes('/espn/public/claims')) return json(200, owners);
    if (url.endsWith('/espn/claims/suggestions')) return json(200, suggestion());
    if (url.endsWith('/espn/claims') && options.method === 'POST') return claim(JSON.parse(options.body));
    if (url.includes('/espn/claims/') && options.method === 'DELETE') return json(200, {});
    return json(404, null);
  }));
  return calls;
}
const view = () => render(<MemoryRouter initialEntries={['/fantasy']}><Routes><Route path="/fantasy/*" element={<Fantasy />} /></Routes></MemoryRouter>);
const teams = [{ team_id: 1, name: 'Harbor Hoopers', manager: 'Jordan', score: 0.95, claimed: false, mine: false, can_claim: true },
  { team_id: 2, name: 'Lob City', manager: 'Paulo', score: 0.1, claimed: false, mine: false, can_claim: false }];

describe('team links', () => {
  afterEach(() => { vi.unstubAllGlobals(); globalThis.__session = null; });

  it('shows ESPN manager first names, and the Dice name once a team is confirmed', async () => {
    server({ owners: [{ team_id: 2, display_name: 'Paulo R', avatar_url: 'https://cdn.example/p.png' }], suggestion: () => ({}) });
    view();
    expect((await screen.findAllByText('Jordan')).length).toBeGreaterThan(0);
    expect((await screen.findAllByText('Paulo R')).length).toBeGreaterThan(0);
    expect(screen.queryByText('Paulo')).toBeNull();
    expect(await screen.findByRole('button', { name: 'Sign in to link your Dice profile' })).toBeTruthy();
  });

  it('suggests the matching team, links it on confirm, and can unlink', async () => {
    globalThis.__session = session;
    let mine = null;
    const calls = server({ suggestion: () => ({ season: 2027, has_profile: true, mine, teams: teams.map(t => ({ ...t, mine: mine?.team_id === t.team_id, claimed: mine?.team_id === t.team_id })) }) });
    view();
    const confirm = await screen.findByRole('button', { name: 'That’s me' });
    expect(screen.getByText(/Is this you\?/).textContent).toContain('Harbor Hoopers');
    mine = { team_id: 1 };
    fireEvent.click(confirm);
    expect((await screen.findByText(/Linked to/)).textContent).toContain('Harbor Hoopers');
    expect(calls).toContainEqual(['https://api.example.test/espn/claims', 'POST']);
    mine = null;
    fireEvent.click(screen.getByRole('button', { name: 'Unlink' }));
    await waitFor(() => expect(calls).toContainEqual(['https://api.example.test/espn/claims/2027/1', 'DELETE']));
  });

  it('asks for a Dice profile before offering a link', async () => {
    globalThis.__session = session;
    server({ suggestion: () => ({ season: 2027, has_profile: false, mine: null, teams }) });
    view();
    expect(await screen.findByText(/Make a Dice profile first/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'That’s me' })).toBeNull();
  });

  it('only offers teams the server allows and explains a refusal', async () => {
    globalThis.__session = session;
    server({ suggestion: () => ({ season: 2027, has_profile: true, mine: null, teams }),
      claim: () => json(403, { detail: 'name_mismatch' }) });
    view();
    const options = await screen.findAllByRole('option');
    expect(options.map(o => o.textContent)).toEqual(['Choose…', 'Harbor Hoopers (Jordan)']);
    fireEvent.click(screen.getByRole('button', { name: 'That’s me' }));
    expect((await screen.findByRole('alert')).textContent).toMatch(/doesn’t match your profile/);
  });

  it('says linking is unavailable instead of vanishing', async () => {
    globalThis.__session = session;
    server({ suggestion: () => { throw new Error('down'); } });
    view();
    expect(await screen.findByText(/Team linking isn’t available/)).toBeTruthy();
  });
});
