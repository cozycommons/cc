import React, { Suspense } from 'react';
import { render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { lazyWithRecovery } from './lazyWithRecovery.js';
import ChunkErrorBoundary from './ChunkErrorBoundary.jsx';
import { recoverChunkLoad } from './chunkRecovery.js';

vi.mock('./chunkRecovery.js', () => ({ recoverChunkLoad: vi.fn(() => false) }));
afterEach(() => { vi.restoreAllMocks(); });
it('handles lazy rejection and shows an error when the reload budget is exhausted', async () => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
  const error = new Error('Failed to fetch dynamically imported module: /assets/old.js');
  const importer = vi.fn().mockRejectedValue(error);
  const Page = lazyWithRecovery(importer);
  render(<ChunkErrorBoundary><Suspense fallback={null}><Page /></Suspense></ChunkErrorBoundary>);
  expect(await screen.findByRole('alert')).toHaveTextContent('This page couldn’t load');
  expect(importer).toHaveBeenCalledOnce();
  expect(recoverChunkLoad).toHaveBeenCalledWith(error);
});
