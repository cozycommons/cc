import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import DesignIndex from './DesignIndex.jsx';

describe('Cozy Commons design system', () => {
  afterEach(cleanup);

  const renderPage = () => render(<MemoryRouter><DesignIndex /></MemoryRouter>);

  it('switches between component views', async () => {
    const user = userEvent.setup();
    renderPage();

    expect(screen.getByRole('tabpanel')).toHaveTextContent('The lamp is a local pool of amber.');
    await user.click(screen.getByRole('tab', { name: 'records' }));

    expect(screen.getByRole('tab', { name: 'records' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tabpanel')).toHaveTextContent('Dice keeps the friendly arguments.');
  });

  it('changes the comparison with native keyboard selection', async () => {
    const user = userEvent.setup();
    renderPage();
    const week = screen.getByRole('radio', { name: 'Week' });
    week.focus();
    await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('radio', { name: 'Month' })).toBeChecked();
    expect(screen.getByRole('group', { name: 'Schedule completion' })).toHaveTextContent('64 played');
    expect(screen.getByRole('group', { name: 'Schedule completion' })).toHaveTextContent('28 remaining');
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

    await user.click(screen.getByRole('button', { name: 'confirm locally' }));
    expect(screen.getByText('A few small details need your attention.')).toBeInTheDocument();

    await user.type(screen.getByLabelText(/your name/), 'Mina');
    await user.type(screen.getByLabelText('email required', { exact: true }), 'mina@example.com');
    await user.selectOptions(screen.getByLabelText(/record type/), 'round');
    await user.click(screen.getByLabelText('I understand this is demo data.'));
    await user.click(screen.getByRole('button', { name: 'confirm locally' }));

    expect(screen.getByText('Confirmed locally — demo record ready; nothing was sent.')).toBeInTheDocument();
  });

  it('opens and closes the local dialog', async () => {
    const user = userEvent.setup();
    renderPage();

    await user.click(screen.getByRole('button', { name: 'open dialog' }));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'not now' }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
