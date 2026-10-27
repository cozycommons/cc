import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import OAuthConsent from './OAuthConsent';

let auth;
vi.mock('./useCozyAuth', () => ({ useCozyAuth: () => auth }));
const authorizationId = 'authorization-1';
const details = {
  authorization_id: authorizationId,
  client: { id: 'client-1', name: 'Cozy Commons MCP', logo_uri: 'https://untrusted.example/logo' },
  redirect_uri: 'https://api.example.test/callback',
  user: { id: 'user-1', email: 'person@example.test' },
  scope: 'openid email',
};
const redirect = vi.fn();

function openConsent(path = `/oauth/consent?authorization_id=${authorizationId}`) {
  return render(<MemoryRouter initialEntries={[path]}><OAuthConsent onRedirect={redirect} /></MemoryRouter>);
}

describe('OAuth consent', () => {
  beforeEach(() => {
    redirect.mockReset();
    auth = {
      user: details.user, loading: false, signIn: vi.fn().mockResolvedValue(),
      supabase: { auth: { oauth: {
        getAuthorizationDetails: vi.fn().mockResolvedValue({ data: details, error: null }),
        approveAuthorization: vi.fn().mockResolvedValue({ data: { redirect_url: 'https://api.example.test/callback?code=code-1' }, error: null }),
        denyAuthorization: vi.fn().mockResolvedValue({ data: { redirect_url: 'https://api.example.test/callback?error=access_denied' }, error: null }),
      } } },
    };
  });

  it.each(['/oauth/consent', '/oauth/consent?authorization_id=..%2Fadmin'])('rejects missing or malformed request IDs: %s', (path) => {
    openConsent(path);
    expect(screen.getByRole('alert')).toHaveTextContent('Missing or invalid connection request');
    expect(auth.supabase.auth.oauth.getAuthorizationDetails).not.toHaveBeenCalled();
  });

  it('requires sign-in before loading the request', async () => {
    auth.user = null;
    openConsent();
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    await waitFor(() => expect(auth.signIn).toHaveBeenCalledOnce());
    expect(auth.supabase.auth.oauth.getAuthorizationDetails).not.toHaveBeenCalled();
  });

  it('shows the requesting application and scopes without approving automatically or loading its logo', async () => {
    openConsent();
    expect(await screen.findByText('Cozy Commons MCP')).toBeInTheDocument();
    expect(screen.getByText('person@example.test')).toBeInTheDocument();
    expect(screen.getByText('openid')).toBeInTheDocument();
    expect(screen.getByText('email')).toBeInTheDocument();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    expect(auth.supabase.auth.oauth.approveAuthorization).not.toHaveBeenCalled();
    expect(redirect).not.toHaveBeenCalled();
  });

  it.each([
    ['Allow connection', 'approveAuthorization', 'https://api.example.test/callback?code=code-1'],
    ['Deny', 'denyAuthorization', 'https://api.example.test/callback?error=access_denied'],
  ])('submits %s and follows the validated provider response', async (button, method, url) => {
    openConsent();
    fireEvent.click(await screen.findByRole('button', { name: button }));
    await waitFor(() => expect(redirect).toHaveBeenCalledWith(url));
    expect(auth.supabase.auth.oauth[method]).toHaveBeenCalledWith(authorizationId, { skipBrowserRedirect: true });
  });

  it('continues an already approved request', async () => {
    auth.supabase.auth.oauth.getAuthorizationDetails.mockResolvedValue({ data: { redirect_url: 'https://api.example.test/callback?code=existing' }, error: null });
    openConsent();
    await waitFor(() => expect(redirect).toHaveBeenCalledWith('https://api.example.test/callback?code=existing'));
    expect(auth.supabase.auth.oauth.approveAuthorization).not.toHaveBeenCalled();
  });

  it('rejects unsafe redirect schemes', async () => {
    auth.supabase.auth.oauth.getAuthorizationDetails.mockResolvedValue({ data: { redirect_url: 'javascript:alert(1)' }, error: null });
    openConsent();
    expect(await screen.findByRole('alert')).toHaveTextContent('unsupported redirect address');
    expect(redirect).not.toHaveBeenCalled();
  });

  it('does not display consent for another signed-in account', async () => {
    auth.supabase.auth.oauth.getAuthorizationDetails.mockResolvedValue({ data: { ...details, user: { id: 'different-user' } }, error: null });
    openConsent();
    expect(await screen.findByRole('alert')).toHaveTextContent('connection request is invalid');
    expect(screen.queryByRole('button', { name: 'Allow connection' })).not.toBeInTheDocument();
  });

  it('shows an expired-request error and lets the user retry', async () => {
    auth.supabase.auth.oauth.getAuthorizationDetails.mockResolvedValueOnce({ data: null, error: new Error('Connection request expired.') });
    openConsent();
    expect(await screen.findByRole('alert')).toHaveTextContent('Connection request expired');
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByRole('button', { name: 'Allow connection' })).toBeInTheDocument();
  });

  it('keeps the decision visible after approval fails', async () => {
    auth.supabase.auth.oauth.approveAuthorization.mockResolvedValue({ data: null, error: new Error('Network unavailable.') });
    openConsent();
    fireEvent.click(await screen.findByRole('button', { name: 'Allow connection' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Network unavailable');
    expect(screen.getByRole('button', { name: 'Allow connection' })).toBeEnabled();
    expect(redirect).not.toHaveBeenCalled();
  });

  it('does not navigate away from a different page after the consent component unmounts', async () => {
    let finish;
    auth.supabase.auth.oauth.approveAuthorization.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
    const view = openConsent();
    fireEvent.click(await screen.findByRole('button', { name: 'Allow connection' }));
    view.unmount();
    await act(async () => finish({ data: { redirect_url: 'https://api.example.test/callback?code=code-1' }, error: null }));
    expect(redirect).not.toHaveBeenCalled();
  });
});
