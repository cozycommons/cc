import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api.js', () => ({
  diceApi: {
    getPhotos: vi.fn(),
  },
}));

import { diceApi } from '../api.js';
import PhotoGallery, { getSwipeDirection } from './PhotoGallery.jsx';

const photos = [
  {
    id: 'photo-1',
    image_url: 'https://storage.example/photos/user-1/upload-1/display.webp',
    display_name: 'Alice',
    created_at: '2026-07-20T12:00:00Z',
    game_id: 'game-1',
  },
  {
    id: 'photo-2',
    image_url: 'https://example.com/two.jpg',
    display_name: 'Bob',
    created_at: '2026-07-21T12:00:00Z',
    game_id: 'game-2',
  },
  {
    id: 'photo-3',
    image_url: 'https://example.com/three.jpg',
    display_name: 'Cara',
    created_at: '2026-07-22T12:00:00Z',
    game_id: 'game-3',
  },
];

function renderGallery() {
  return render(
    <MemoryRouter>
      <PhotoGallery />
    </MemoryRouter>,
  );
}

describe('PhotoGallery', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    diceApi.getPhotos.mockResolvedValue(photos);
  });

  it('navigates between photos with controls and wraps at the ends', async () => {
    renderGallery();

    const firstPhoto = await screen.findByRole('button', { name: 'Open photo 1 of 3' });
    expect(within(firstPhoto).getByRole('img')).toHaveAttribute(
      'src',
      'https://storage.example/photos/user-1/upload-1/thumb.webp',
    );
    fireEvent.click(firstPhoto);
    const dialog = screen.getByRole('dialog', { name: 'Photo viewer' });
    expect(within(dialog).getByRole('img', { name: 'Photo by Alice' })).toBeInTheDocument();
    expect(within(dialog).getByRole('link', { name: 'Download original' })).toHaveAttribute(
      'href',
      'https://storage.example/photos/user-1/upload-1/original?download=dice-photo-original',
    );

    fireEvent.click(screen.getByRole('button', { name: 'Previous photo' }));
    expect(within(dialog).getByRole('img', { name: 'Photo by Cara' })).toBeInTheDocument();
    expect(within(dialog).getByText('3 / 3')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Next photo' }));
    expect(within(dialog).getByRole('img', { name: 'Photo by Alice' })).toBeInTheDocument();
  });

  it('supports arrow-key navigation and Escape to close', async () => {
    renderGallery();

    const opener = await screen.findByRole('button', { name: 'Open photo 2 of 3' });
    opener.focus();
    fireEvent.click(opener);
    const dialog = screen.getByRole('dialog', { name: 'Photo viewer' });
    expect(within(dialog).getByRole('button', { name: 'Close' })).toHaveFocus();

    fireEvent.keyDown(window, { key: 'ArrowRight' });
    expect(within(dialog).getByRole('img', { name: 'Photo by Cara' })).toBeInTheDocument();

    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByRole('dialog', { name: 'Photo viewer' })).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });

  it('recognizes horizontal swipes and ignores short or vertical gestures', () => {
    expect(getSwipeDirection({ x: 200, y: 100 }, { x: 120, y: 105 })).toBe(1);
    expect(getSwipeDirection({ x: 120, y: 100 }, { x: 200, y: 105 })).toBe(-1);
    expect(getSwipeDirection({ x: 120, y: 100 }, { x: 140, y: 105 })).toBeNull();
    expect(getSwipeDirection({ x: 120, y: 100 }, { x: 200, y: 210 })).toBeNull();
  });

  it('loads the first gallery row eagerly and defers the rest', async () => {
    diceApi.getPhotos.mockResolvedValue(Array.from({ length: 8 }, (_, index) => ({
      ...photos[index % photos.length],
      id: `photo-${index}`,
      image_url: `https://example.com/${index}.jpg`,
    })));
    renderGallery();

    const images = await screen.findAllByRole('img');
    expect(images.slice(0, 6).every((image) => image.getAttribute('loading') === 'eager')).toBe(true);
    expect(images.slice(6).every((image) => image.getAttribute('loading') === 'lazy')).toBe(true);
    expect(images.every((image) => image.getAttribute('decoding') === 'async')).toBe(true);
  });
});
