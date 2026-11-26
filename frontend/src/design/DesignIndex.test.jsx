import React from 'react';
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import { createAgent } from '@ui-sdk/react/agent';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import DesignIndex from './DesignIndex.jsx';

describe('Cozy Commons design system', () => {
  // jsdom omits browser APIs used to settle and position SDK overlays.
  if (!Element.prototype.getAnimations) Element.prototype.getAnimations = () => [];
  if (!globalThis.CSS.supports) globalThis.CSS.supports = () => false;
  HTMLElement.prototype.showPopover = () => {};
  HTMLElement.prototype.hidePopover = () => {};
  Element.prototype.checkVisibility = function () { return this.isConnected && !this.hidden; };
  document.head.append(Object.assign(document.createElement('style'), {
    textContent: '[popover][data-open] { display: block !important; }',
  }));
  afterEach(cleanup);

  const renderPage = () => render(<MemoryRouter><DesignIndex /></MemoryRouter>);

  it('switches between component views', async () => {
    const user = userEvent.setup();
    renderPage();

    expect(screen.getByRole('tabpanel')).toHaveTextContent('The lamp is a local pool of amber.');
    await user.click(screen.getByRole('tab', { name: 'records' }));

    expect(screen.getByRole('tab', { name: 'records' })).toHaveAttribute('aria-selected', 'true');
    expect(await screen.findByRole('tabpanel', { name: 'records' })).toHaveTextContent('Dice keeps the friendly arguments.');
  });

  it('changes the comparison with SDK keyboard selection', async () => {
    const user = userEvent.setup();
    renderPage();
    const week = screen.getByRole('radio', { name: 'Week' });
    week.focus();
    await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('radio', { name: 'Month' })).toBeChecked();
    expect(screen.getByRole('group', { name: 'Schedule completion' })).toHaveTextContent('64 played');
    expect(screen.getByRole('group', { name: 'Schedule completion' })).toHaveTextContent('28 remaining');
  });

  it('lets the SDK discover and fill a labeled design-system field', async () => {
    renderPage();
    const agent = createAgent();
    const field = screen.getByRole('searchbox', { name: 'search records' });
    await act(async () => {
      const result = await agent.act({ steps: [{ ref: 'search records', action: 'setValue', args: ['patio rematch'] }] });
      expect(result.ok).toBe(true);
    });
    expect(field).toHaveValue('patio rematch');
  });

  it('keeps the previous total visible throughout a refresh', async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole('button', { name: 'Preview refresh' }));
    expect(screen.getByRole('button', { name: 'Refreshing…' })).toBeDisabled();
    expect(screen.getByText('24 games')).toBeVisible();
    expect(screen.getByText('Loading sample activity')).toBeInTheDocument();
    expect(await screen.findByText('Sample updated just now.', {}, { timeout: 2500 })).toBeVisible();
    expect(screen.getByRole('button', { name: 'Preview refresh' })).toBeEnabled();
  });

  it('keeps the demo form local and validates required fields', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole('button', { name: 'Confirm locally' }));
    expect(screen.getByText('A few small details need your attention.')).toBeInTheDocument();

    await user.type(screen.getByLabelText(/your name/), 'Mina');
    await user.type(screen.getByLabelText('email required', { exact: true }), 'mina@example.com');
    await user.click(screen.getByRole('combobox', { name: 'record type required' }));
    await user.click(await screen.findByRole('option', { name: 'round', exact: true }));
    await user.click(screen.getByLabelText('I understand this is demo data.'));
    await user.click(screen.getByRole('button', { name: 'Confirm locally' }));

    expect(screen.getByText('Confirmed locally — demo record ready; nothing was sent.')).toBeInTheDocument();
  });

  it('opens and closes the local dialog', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole('button', { name: 'Open dialog' }));
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'Not now' }));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });
});
