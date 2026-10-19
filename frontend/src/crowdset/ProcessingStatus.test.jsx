import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import ProcessingStatus from './ProcessingStatus';

afterEach(cleanup);

it('shows measured rendering progress and a rendering-only estimate', () => {
  const { rerender } = render(<ProcessingStatus set={{ stage: 'Rendering video…', processing: {
    phase: 'render', percent: 37, remaining_seconds: 3600, started_at: Date.now() / 1000 - 600,
  } }} />);
  expect(screen.getByRole('progressbar', { name: 'Video rendering' })).toHaveAttribute('value', '37');
  expect(screen.getByText('Render video')).toHaveAttribute('aria-current', 'step');
  expect(screen.getByText(/of video rendering left/)).toBeInTheDocument();
  rerender(<ProcessingStatus set={{ stage: 'Saving the finished cut…', processing: { phase: 'save' } }} />);
  expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
  expect(screen.getByRole('status')).toHaveTextContent('Saving the finished cut');
  expect(screen.getByText('Save')).toHaveAttribute('aria-current', 'step');
});

it('does not invent percentages or estimates for legacy or preparation stages', () => {
  render(<ProcessingStatus set={{ stage: 'Preparing recording 1 of 50…' }} />);
  expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
  expect(screen.queryByText(/rendering left/)).not.toBeInTheDocument();
  expect(screen.getByRole('status')).toHaveTextContent('Preparing recording 1 of 50');
  expect(screen.getByText(/Processing continues on the server/)).toBeInTheDocument();
});

it('replaces an outdated estimate with an honest progress-update message', () => {
  render(<ProcessingStatus set={{ stage: 'Rendering video…', processing: {
    phase: 'render', percent: 37, remaining_seconds: 60, updated_at: Date.now() / 1000 - 300,
  } }} />);
  expect(screen.queryByText(/rendering left/)).not.toBeInTheDocument();
  expect(screen.getByText(/No new render progress in/)).toBeInTheDocument();
});
