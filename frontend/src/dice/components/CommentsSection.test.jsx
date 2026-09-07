import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../../contexts/SupabaseContext', () => ({
  useSupabase: vi.fn(),
}));

vi.mock('../api.js', () => ({
  diceApi: {
    getComments: vi.fn(),
    postComment: vi.fn(),
    deleteComment: vi.fn(),
  },
}));

vi.mock('../imageUpload.js', () => ({
  COMMENT_IMAGE_MAX_EDGE: 1600,
  COMMENT_THUMB_MAX_EDGE: 480,
  compactImageVariants: vi.fn(),
  imageVariantUrl: (url) => url,
  uniqueImageFolder: () => 'user-1/upload-1',
}));

import { useSupabase } from '../../contexts/SupabaseContext';
import { diceApi } from '../api.js';
import { compactImageVariants } from '../imageUpload.js';
import CommentsSection from './CommentsSection.jsx';

describe('CommentsSection photo upload', () => {
  const upload = vi.fn();
  const getPublicUrl = vi.fn((path) => ({ data: { publicUrl: `https://storage.example/${path}` } }));

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn(() => 'blob:preview'),
      revokeObjectURL: vi.fn(),
    });
    upload.mockResolvedValue({ error: null });
    useSupabase.mockReturnValue({
      supabase: {
        storage: {
          from: () => ({ upload, getPublicUrl }),
        },
      },
    });
    diceApi.getComments.mockResolvedValue([]);
    diceApi.postComment.mockResolvedValue({});
    compactImageVariants.mockResolvedValue([
      new Blob(['display'], { type: 'image/webp' }),
      new Blob(['thumb'], { type: 'image/webp' }),
    ]);
  });

  it('stores the original and both cached derivatives, then records the display URL', async () => {
    const { container } = render(
      <CommentsSection
        gameId="game-1"
        auth={{ user: { id: 'user-1' }, token: 'token', isAdmin: false }}
      />,
    );
    await screen.findByText('No comments yet.');

    const original = new File(['photo'], 'game.jpg', { type: 'image/jpeg' });
    fireEvent.change(container.querySelector('input[type="file"]'), {
      target: { files: [original] },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Post Comment' }));

    await waitFor(() => expect(diceApi.postComment).toHaveBeenCalled());
    expect(compactImageVariants).toHaveBeenCalledWith(original, [
      { maxEdge: 1600 },
      { maxEdge: 480, quality: 0.74 },
    ]);
    expect(upload.mock.calls.map(([path]) => path)).toEqual([
      'user-1/upload-1/original',
      'user-1/upload-1/display.webp',
      'user-1/upload-1/thumb.webp',
    ]);
    expect(upload.mock.calls.every(([, , options]) => options.cacheControl === '31536000')).toBe(true);
    expect(diceApi.postComment).toHaveBeenCalledWith(
      'token',
      'game-1',
      null,
      'https://storage.example/user-1/upload-1/display.webp',
    );
  });
});
