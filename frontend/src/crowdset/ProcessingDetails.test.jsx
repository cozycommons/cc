import React from 'react';
import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, expect, it } from 'vitest';
import ProcessingDetails from './ProcessingDetails';

afterEach(cleanup);
it('keeps technical progress collapsed and shows measured GPU details', () => {
  const { container } = render(<ProcessingDetails set={{ status: 'processing', processing: {
    engine: 'h264_nvenc', completed: 240, total: 2400, fps: 48,
  }, processing_events: [{ at: 100, message: 'PC worker claimed the job' }] }} />);
  expect(container.querySelector('details')).not.toHaveAttribute('open');
  expect(screen.getByText('PC · NVIDIA GPU')).toBeInTheDocument();
  expect(screen.getByText('48.0 fps · 2.0× playback')).toBeInTheDocument();
  expect(screen.getByRole('list', { name: 'Processing events' })).toHaveTextContent('PC worker claimed the job');
});
