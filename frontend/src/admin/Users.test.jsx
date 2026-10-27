import React from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import Users from './Users.jsx';
import { adminRequest } from './api.js';
vi.mock('./api.js', () => ({ adminRequest: vi.fn() }));
const member = { user_id: 'member-id', email: 'member@example.test', display_name: 'Taylor', role: 'member', verified: true };
let onAccessLost, onRoleChanged;
beforeEach(() => {
  onAccessLost = vi.fn(); onRoleChanged = vi.fn();
  adminRequest.mockReset();
  adminRequest.mockImplementation(async (path) => path === '/role-history' ? [] : { users: [member], has_more: false });
});
afterEach(cleanup);
function show() { render(<Users onAccessLost={onAccessLost} onRoleChanged={onRoleChanged} />); }
it('requires confirmation, can cancel, and sends the expected old role', async () => {
  show();
  fireEvent.click(await screen.findByRole('button', { name: 'Make member@example.test an admin' }));
  expect(screen.getByRole('region', { name: 'Confirm role change' })).toHaveTextContent('member@example.test');
  expect(screen.getByRole('button', { name: 'Confirm role change' })).toHaveFocus();
  expect(adminRequest.mock.calls.some(([, options]) => options?.method === 'PUT')).toBe(false);
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  fireEvent.click(screen.getByRole('button', { name: 'Make member@example.test an admin' }));
  fireEvent.click(screen.getByRole('button', { name: 'Confirm role change' }));
  await waitFor(() => expect(onRoleChanged).toHaveBeenCalledOnce());
  expect(adminRequest).toHaveBeenCalledWith('/users/member-id/role', { method: 'PUT', body: { role: 'admin', expected_role: 'member' } });
});
it('searches and pages using the server directory', async () => {
  adminRequest.mockImplementation(async (path) => path === '/role-history' ? [] : { users: [member], has_more: true });
  show();
  await screen.findByText('Taylor');
  fireEvent.change(screen.getByLabelText('Search users'), { target: { value: 'Taylor & Co' } });
  fireEvent.click(screen.getByRole('button', { name: 'Search', exact: true }));
  await waitFor(() => expect(adminRequest).toHaveBeenCalledWith('/users?search=Taylor%20%26%20Co&offset=0', expect.any(Object)));
  fireEvent.click(await screen.findByRole('button', { name: 'Next' }));
  await waitFor(() => expect(adminRequest).toHaveBeenCalledWith('/users?search=Taylor%20%26%20Co&offset=50', expect.any(Object)));
});
it('preserves a rejected edit and lets the admin refresh', async () => {
  show();
  fireEvent.click(await screen.findByRole('button', { name: 'Make member@example.test an admin' }));
  adminRequest.mockRejectedValueOnce(Object.assign(new Error('Role changed. Refresh before trying again.'), { status: 409 }));
  fireEvent.click(screen.getByRole('button', { name: 'Confirm role change' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Role changed');
  expect(screen.getByRole('region', { name: 'Confirm role change' })).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: 'Refresh users' }));
  await waitFor(() => expect(screen.queryByRole('region', { name: 'Confirm role change' })).not.toBeInTheDocument());
});
it('denies unverified promotion and reports revoked access', async () => {
  adminRequest.mockImplementation(async (path) => path === '/role-history' ? [] : { users: [{ ...member, verified: false }], has_more: false });
  show();
  expect(await screen.findByRole('button', { name: 'Make member@example.test an admin' })).toBeDisabled();
  adminRequest.mockRejectedValue(Object.assign(new Error('Access denied.'), { status: 403 }));
  fireEvent.click(screen.getByRole('button', { name: 'Refresh users' }));
  await waitFor(() => expect(onAccessLost).toHaveBeenCalledWith(403));
});
it('ignores an old search response after a new search', async () => {
  let resolveFirst;
  adminRequest.mockImplementation((path) => {
    if (path === '/role-history') return Promise.resolve([]);
    if (path === '/users?search=&offset=0') return new Promise((resolve) => { resolveFirst = resolve; });
    return Promise.resolve({ users: [], has_more: false });
  });
  show();
  fireEvent.change(screen.getByLabelText('Search users'), { target: { value: 'nobody' } });
  fireEvent.click(screen.getByRole('button', { name: 'Search', exact: true }));
  expect(await screen.findByText('No users found')).toBeInTheDocument();
  resolveFirst({ users: [member], has_more: false });
  await waitFor(() => expect(screen.queryByText('Taylor')).not.toBeInTheDocument());
});

it('allows revoking an assigned admin whose account is no longer verified', async () => {
  adminRequest.mockImplementation(async (path) => path === '/role-history' ? [] : { users: [{ ...member, role: 'admin', verified: false }], has_more: false });
  show();
  expect(await screen.findByRole('button', { name: 'Make member@example.test a member' })).toBeEnabled();
});
