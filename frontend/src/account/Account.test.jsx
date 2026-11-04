import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import Account from './Account.jsx';

const mocked = vi.hoisted(() => ({ identity: null, request: vi.fn(), shown: vi.fn(), signIn: vi.fn() }));
vi.mock('../components/commonsIdentity.js', () => ({
  useCommonsIdentity: () => mocked.identity,
  accountRequest: (...args) => mocked.request(...args),
  showCommonsProfile: (...args) => mocked.shown(...args),
  signInToCommons: (...args) => mocked.signIn(...args),
  signOutOfCommons: vi.fn(),
  commonsSupabase: () => null,
}));

const sam = { user_id: 'u1', display_name: 'Sam', email: 'sam@example.test', avatar_url: null };
const claude = { id: 'c1', client_name: 'Claude', redirect_host: 'claude.ai', scopes: ['commons:read', 'commons:edit'],
  approved_at: '2026-10-04T12:00:00Z', last_used_at: '2026-11-02T12:00:00Z' };

beforeEach(() => {
  mocked.identity = { status: 'signed-in', user: { id: 'u1' }, profile: sam };
  mocked.request.mockReset(); mocked.shown.mockReset(); mocked.signIn.mockReset();
});
afterEach(cleanup);
const open = () => render(<MemoryRouter initialEntries={['/account']}><Account /></MemoryRouter>);

it('asks signed-out visitors to sign in', () => {
  mocked.identity = { status: 'signed-out', user: null, profile: null };
  open();
  fireEvent.click(screen.getByRole('button', { name: 'Continue with Google' }));
  expect(mocked.signIn).toHaveBeenCalled();
  expect(mocked.request).not.toHaveBeenCalled();
});

it('renames the Commons profile and shows it in the header', async () => {
  mocked.request.mockImplementation(async (path) => (path === '/connections' ? [] : { ...sam, display_name: 'Sam H' }));
  open();
  fireEvent.click(screen.getByRole('button', { name: 'Edit name' }));
  fireEvent.change(screen.getByRole('textbox', { name: 'Display name' }), { target: { value: '  Sam H ' } });
  fireEvent.click(screen.getByRole('button', { name: 'Save' }));
  await waitFor(() => expect(mocked.shown).toHaveBeenCalledWith(expect.objectContaining({ display_name: 'Sam H' })));
  expect(mocked.request).toHaveBeenCalledWith('/profile', { method: 'PATCH', body: { display_name: 'Sam H' } });
  expect(await screen.findByRole('button', { name: 'Edit name' })).toBeInTheDocument();
});

it('lists connected agents and disconnects one after confirming', async () => {
  mocked.request.mockImplementation(async (path) => (path === '/connections' ? [claude] : null));
  open();
  const row = (await screen.findByText('Claude')).closest('li');
  expect(row).toHaveTextContent('claude.ai');
  expect(row).toHaveTextContent('Read and save changes');
  fireEvent.click(within(row).getByRole('button', { name: 'Disconnect' }));
  fireEvent.click(within(row).getByRole('button', { name: 'Disconnect Claude' }));
  await waitFor(() => expect(screen.queryByText('Claude')).not.toBeInTheDocument());
  expect(mocked.request).toHaveBeenCalledWith('/connections/c1', { method: 'DELETE' });
  expect(screen.getByText('No agents connected.')).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Setup steps' })).toHaveAttribute('href', '/connect');
});

it('shows why connections are unavailable and keeps the profile usable', async () => {
  mocked.request.mockImplementation(async (path) => {
    if (path === '/connections') throw new Error('Agent connections are unavailable.');
    return { beli: null };
  });
  open();
  expect(await screen.findByRole('alert')).toHaveTextContent('Agent connections are unavailable.');
  expect(screen.getByRole('button', { name: 'Edit name' })).toBeInTheDocument();
});

const openAt = (entry) => render(<MemoryRouter initialEntries={[entry]}><Account /></MemoryRouter>);

it("connects Beli on the page an agent's #beli link opens, without keeping the password", async () => {
  mocked.request.mockImplementation(async (path) => {
    if (path === '/connections') return [];
    if (path === '/linked-accounts') return { beli: null, resy: null, espn: null, partiful: null };
    return { status: 'linked', account: { id: 'b1', label: 'beli' } };
  });
  openAt('/account#beli');
  const row = (await screen.findByText('Beli')).closest('li');
  fireEvent.change(within(row).getByLabelText('Beli email or phone'), { target: { value: ' sam@example.test ' } });
  fireEvent.change(within(row).getByLabelText('Beli password'), { target: { value: 'synthetic-password' } });
  fireEvent.click(within(row).getByRole('button', { name: 'Connect Beli' }));
  expect(await within(row).findByText('Connected')).toBeInTheDocument();
  expect(mocked.request).toHaveBeenCalledWith('/linked-accounts/beli',
    { method: 'POST', body: { login: 'sam@example.test', password: 'synthetic-password' } });
  expect(within(row).queryByLabelText('Beli password')).not.toBeInTheDocument();
  expect(within(row).getByRole('button', { name: 'Update password' })).toBeInTheDocument();
  const resy = screen.getByText('Resy').closest('li');
  expect(within(resy).queryByLabelText('Resy password')).not.toBeInTheDocument();
});

it('shows a Beli refusal and clears the password for another try', async () => {
  mocked.request.mockImplementation(async (path) => {
    if (path === '/connections') return [];
    if (path === '/linked-accounts') return { beli: { id: 'b1', label: 'beli' }, resy: null, espn: null, partiful: null };
    throw new Error('Beli did not accept that email or phone number and password.');
  });
  openAt('/account');
  const row = (await screen.findByText('Beli')).closest('li');
  fireEvent.click(within(row).getByRole('button', { name: 'Update password' }));
  fireEvent.change(within(row).getByLabelText('Beli email or phone'), { target: { value: 'sam@example.test' } });
  fireEvent.change(within(row).getByLabelText('Beli password'), { target: { value: 'wrong' } });
  fireEvent.click(within(row).getByRole('button', { name: 'Save password' }));
  expect(await within(row).findByRole('alert')).toHaveTextContent('did not accept');
  expect(within(row).getByLabelText('Beli password')).toHaveValue('');
  expect(within(row).getByText('Connected')).toBeInTheDocument();
});

it("connects Resy on the page an agent's #resy link opens, leaving Beli closed", async () => {
  mocked.request.mockImplementation(async (path) => {
    if (path === '/connections') return [];
    if (path === '/linked-accounts') return { beli: null, resy: null, espn: null, partiful: null };
    return { status: 'linked', account: { id: 'r1', label: 'resy' } };
  });
  openAt('/account#resy');
  const row = (await screen.findByText('Resy')).closest('li');
  expect(row).toHaveAttribute('id', 'resy');
  expect(within(screen.getByText('Beli').closest('li')).queryByLabelText('Beli password')).not.toBeInTheDocument();
  expect(within(row).getByLabelText('Resy email')).toHaveAttribute('type', 'email');
  fireEvent.change(within(row).getByLabelText('Resy email'), { target: { value: ' sam@example.test ' } });
  fireEvent.change(within(row).getByLabelText('Resy password'), { target: { value: 'synthetic-password' } });
  fireEvent.click(within(row).getByRole('button', { name: 'Connect Resy' }));
  expect(await within(row).findByText('Connected')).toBeInTheDocument();
  expect(mocked.request).toHaveBeenCalledWith('/linked-accounts/resy',
    { method: 'POST', body: { login: 'sam@example.test', password: 'synthetic-password' } });
  expect(within(row).queryByLabelText('Resy password')).not.toBeInTheDocument();
});

it('shows a Resy refusal and clears the password', async () => {
  mocked.request.mockImplementation(async (path) => {
    if (path === '/connections') return [];
    if (path === '/linked-accounts') return { beli: null, resy: null, espn: null, partiful: null };
    throw new Error('This Resy account is connected to another Cozy Commons user. Sign in as that user to manage it.');
  });
  openAt('/account#resy');
  const row = (await screen.findByText('Resy')).closest('li');
  fireEvent.change(within(row).getByLabelText('Resy email'), { target: { value: 'kim@example.test' } });
  fireEvent.change(within(row).getByLabelText('Resy password'), { target: { value: 'synthetic-password' } });
  fireEvent.click(within(row).getByRole('button', { name: 'Connect Resy' }));
  expect(await within(row).findByRole('alert')).toHaveTextContent('another Cozy Commons user');
  expect(within(row).getByLabelText('Resy password')).toHaveValue('');
  expect(within(row).getByText('Not connected')).toBeInTheDocument();
});

it('connects ESPN by email, asks which league, and keeps the password only until then', async () => {
  const leagues = [{ league_id: 999, name: 'Synthetic League', team_name: 'Squad' }, { league_id: 1001, name: 'Other League', team_name: 'Squad' }];
  mocked.request.mockImplementation(async (path, options) => {
    if (path === '/connections') return [];
    if (path === '/linked-accounts') return { beli: null, resy: null, espn: null, partiful: null };
    if (!options.body.league_id) return { status: 'league_selection_required', season: 2027, leagues };
    return { status: 'linked', account: { id: 'e1', label: 'espn', league_id: 1001, season: 2027 } };
  });
  openAt('/account#espn');
  const row = (await screen.findByText('ESPN')).closest('li');
  fireEvent.change(within(row).getByLabelText('ESPN email'), { target: { value: ' sam@example.test ' } });
  fireEvent.change(within(row).getByLabelText('ESPN password'), { target: { value: 'synthetic-password' } });
  fireEvent.click(within(row).getByRole('checkbox', { name: 'Set my lineup automatically each day' }));
  fireEvent.click(within(row).getByRole('button', { name: 'Connect ESPN' }));
  const choice = await within(row).findByRole('combobox', { name: 'Which league?' });
  expect(within(row).getByLabelText('ESPN password')).toHaveValue('synthetic-password');
  fireEvent.change(choice, { target: { value: '1001' } });
  fireEvent.click(within(row).getByRole('button', { name: 'Connect this league' }));
  expect(await within(row).findByText('Connected · League 1001, 2027 season')).toBeInTheDocument();
  expect(mocked.request).toHaveBeenNthCalledWith(3, '/linked-accounts/espn', { method: 'POST', body: {
    login: 'sam@example.test', password: 'synthetic-password', enable_automation: false } });
  expect(mocked.request).toHaveBeenNthCalledWith(4, '/linked-accounts/espn', { method: 'POST', body: {
    login: 'sam@example.test', password: 'synthetic-password', league_id: 1001, season: 2027, enable_automation: false } });
  expect(within(row).queryByLabelText('ESPN password')).not.toBeInTheDocument();
});

it('connects ESPN from cookies and clears espn_s2 after a refusal', async () => {
  mocked.request.mockImplementation(async (path) => {
    if (path === '/connections') return [];
    if (path === '/linked-accounts') return { beli: null, resy: null, espn: null, partiful: null };
    throw new Error('This ESPN team was set up earlier with different cookies. Sign in with your ESPN email and password to connect it.');
  });
  openAt('/account#espn');
  const row = (await screen.findByText('ESPN')).closest('li');
  fireEvent.click(within(row).getByRole('button', { name: 'Use cookies instead' }));
  expect(within(row).queryByLabelText('ESPN password')).not.toBeInTheDocument();
  fireEvent.change(within(row).getByLabelText('League ID'), { target: { value: '999' } });
  fireEvent.change(within(row).getByLabelText('Season (ending year)'), { target: { value: '2027' } });
  fireEvent.change(within(row).getByLabelText('espn_s2 cookie'), { target: { value: ' synthetic-s2 ' } });
  fireEvent.change(within(row).getByLabelText('SWID cookie'), { target: { value: '{SYNTHETIC}' } });
  fireEvent.click(within(row).getByRole('button', { name: 'Connect ESPN' }));
  expect(await within(row).findByRole('alert')).toHaveTextContent('different cookies');
  expect(mocked.request).toHaveBeenCalledWith('/linked-accounts/espn/cookies', { method: 'POST', body: {
    league_id: 999, season: 2027, espn_s2: 'synthetic-s2', swid: '{SYNTHETIC}', enable_automation: true } });
  expect(within(row).getByLabelText('espn_s2 cookie')).toHaveValue('');
  expect(within(row).getByLabelText('SWID cookie')).toHaveValue('{SYNTHETIC}');
});

it('connects Partiful with a phone number and then the texted code', async () => {
  mocked.request.mockImplementation(async (path, options) => {
    if (path === '/connections') return [];
    if (path === '/linked-accounts') return { beli: null, resy: null, espn: null, partiful: null };
    if (path === '/linked-accounts/partiful/code') return { status: 'code_sent', phone: '+18185551234' };
    if (options.body.code !== '123456') throw new Error('Partiful did not accept that code. Check it or send a new one.');
    return { status: 'linked', account: { id: 'p1', label: 'partiful' } };
  });
  openAt('/account#partiful');
  const row = (await screen.findByText('Partiful')).closest('li');
  fireEvent.change(within(row).getByLabelText('Partiful phone number'), { target: { value: ' (818) 555-1234 ' } });
  fireEvent.click(within(row).getByRole('button', { name: 'Text me a code' }));
  expect(await within(row).findByText('Code sent to +18185551234.')).toBeInTheDocument();
  expect(mocked.request).toHaveBeenCalledWith('/linked-accounts/partiful/code', { method: 'POST', body: { phone: '(818) 555-1234' } });
  fireEvent.change(within(row).getByLabelText('Code from Partiful'), { target: { value: '000000' } });
  fireEvent.click(within(row).getByRole('button', { name: 'Connect Partiful' }));
  expect(await within(row).findByRole('alert')).toHaveTextContent('did not accept that code');
  expect(within(row).getByLabelText('Code from Partiful')).toHaveValue('');
  fireEvent.change(within(row).getByLabelText('Code from Partiful'), { target: { value: ' 123456 ' } });
  fireEvent.click(within(row).getByRole('button', { name: 'Connect Partiful' }));
  expect(await within(row).findByText('Connected')).toBeInTheDocument();
  expect(mocked.request).toHaveBeenLastCalledWith('/linked-accounts/partiful',
    { method: 'POST', body: { phone: '+18185551234', code: '123456' } });
  expect(within(row).queryByLabelText('Code from Partiful')).not.toBeInTheDocument();
  expect(within(row).getByRole('button', { name: 'Sign in again' })).toBeInTheDocument();
});

it('lets the user change the Partiful number after a code was sent', async () => {
  mocked.request.mockImplementation(async (path) => {
    if (path === '/connections') return [];
    if (path === '/linked-accounts') return { beli: null, resy: null, espn: null, partiful: null };
    return { status: 'code_sent', phone: '+18185551234' };
  });
  openAt('/account#partiful');
  const row = (await screen.findByText('Partiful')).closest('li');
  fireEvent.change(within(row).getByLabelText('Partiful phone number'), { target: { value: '8185551234' } });
  fireEvent.click(within(row).getByRole('button', { name: 'Text me a code' }));
  fireEvent.click(await within(row).findByRole('button', { name: 'Change number' }));
  expect(within(row).getByLabelText('Partiful phone number')).toHaveValue('8185551234');
  expect(within(row).queryByLabelText('Code from Partiful')).not.toBeInTheDocument();
});
