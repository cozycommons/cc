import React from 'react';
import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import DesignIndex from './DesignIndex.jsx';

describe('Cozy Commons design system', () => {
  afterEach(cleanup);

  const renderPage = (entry = '/design') => render(
    <MemoryRouter initialEntries={[entry]}><DesignIndex /></MemoryRouter>,
  );

  it('switches member views and honors the archived deep link', async () => {
    const user = userEvent.setup();
    renderPage('/design?members=archived');

    expect(screen.getByRole('tab', { name: 'Archived' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tabpanel')).toHaveTextContent('No Archived Members');
    await user.click(screen.getByRole('tab', { name: 'Current' }));

    expect(screen.getByRole('tab', { name: 'Current' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('table')).toHaveTextContent('Mina Tan');
  });

  it('changes the comparison with keyboard selection and reports progress', async () => {
    const user = userEvent.setup();
    renderPage();
    const week = screen.getByRole('radio', { name: 'Week' });
    week.focus();
    await user.keyboard('{ArrowRight>}');

    await waitFor(() => expect(screen.getByRole('radio', { name: 'Month' })).toBeChecked());
    await user.keyboard('{/ArrowRight}');
    const comparison = screen.getByRole('group', { name: 'Schedule completion' });
    expect(comparison).toHaveTextContent('64 played');
    expect(comparison).toHaveTextContent('28 remaining');
    expect(within(comparison).getByRole('progressbar')).toHaveAttribute('aria-valuenow', String(64 / 92 * 100));
  });

  it('keeps the previous total visible throughout a refresh', async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByRole('button', { name: 'Preview Refresh' }));
    expect(screen.getByRole('button', { name: 'Refreshing…' })).toBeDisabled();
    expect(screen.getByText('24 games')).toBeVisible();
    expect(screen.getByText('Loading sample activity')).toBeInTheDocument();
    expect(await screen.findByText('Sample updated just now.', {}, { timeout: 2500 })).toBeVisible();
    expect(screen.getByRole('button', { name: 'Preview Refresh' })).toBeEnabled();
  });

  it('focuses the first invalid field and validates the sample form locally', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole('button', { name: 'Save Sample' }));
    expect(screen.getByText('Review the highlighted fields.')).toBeInTheDocument();
    expect(screen.getByLabelText('Name')).toHaveFocus();

    await user.type(screen.getByLabelText('Name'), 'Mina');
    await user.type(screen.getByLabelText('Email'), 'mina@example.com');
    await user.click(screen.getByRole('combobox', { name: 'Record Type' }));
    await user.click(await screen.findByRole('option', { name: 'Round', exact: true }));
    await user.click(screen.getByRole('checkbox', { name: 'Confirm sample data' }));
    await user.click(screen.getByRole('button', { name: 'Save Sample' }));

    expect(screen.getAllByText('Sample record saved locally.').length).toBeGreaterThan(0);
  });

  it('closes the sample dialog with Escape and restores focus', async () => {
    const user = userEvent.setup();
    renderPage();

    const trigger = screen.getByRole('button', { name: 'Open Dialog' });
    await user.click(trigger);
    expect(screen.getByRole('dialog', { name: 'Keep the Sample Note?' })).toBeInTheDocument();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });
});
