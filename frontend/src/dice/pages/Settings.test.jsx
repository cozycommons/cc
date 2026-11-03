import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ updateMyProfile: vi.fn() }));
vi.mock('../api.js', () => ({ diceApi: mocks }));

import Settings from './Settings.jsx';

function renderSettings(profile = { user_id: 'u1', is_anonymous: false }) {
  const auth = { token: 'token', profile, refreshProfile: vi.fn().mockResolvedValue(profile) };
  render(<MemoryRouter><Settings auth={auth} /></MemoryRouter>);
  return auth;
}

describe('Dice settings', () => {
  afterEach(() => vi.restoreAllMocks());

  it('asks before turning on anonymous play, then saves it', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true);
    mocks.updateMyProfile.mockResolvedValue({});
    const auth = renderSettings();
    const toggle = screen.getByRole('checkbox', { name: 'Play anonymously' });

    fireEvent.click(toggle);
    expect(mocks.updateMyProfile).not.toHaveBeenCalled();
    fireEvent.click(toggle);

    await waitFor(() => expect(mocks.updateMyProfile).toHaveBeenCalledWith('token', { is_anonymous: true }));
    expect(auth.refreshProfile).toHaveBeenCalled();
    expect(confirm).toHaveBeenCalledTimes(2);
  });

  it('turns anonymous play off without a confirmation', async () => {
    const confirm = vi.spyOn(window, 'confirm');
    mocks.updateMyProfile.mockResolvedValue({});
    renderSettings({ user_id: 'u1', is_anonymous: true });

    fireEvent.click(screen.getByRole('checkbox', { name: 'Play anonymously' }));

    await waitFor(() => expect(mocks.updateMyProfile).toHaveBeenCalledWith('token', { is_anonymous: false }));
    expect(confirm).not.toHaveBeenCalled();
  });
});
