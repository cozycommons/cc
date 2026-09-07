import { describe, expect, it } from 'vitest';
import {
  AVATAR_IMAGE_MAX_EDGE,
  MAX_ORIGINAL_IMAGE_BYTES,
  compactImage,
  containedImageSize,
  imageVariantUrl,
} from './imageUpload.js';

describe('imageUpload', () => {
  it('keeps avatars large enough for the profile view without shipping camera-sized images', () => {
    expect(AVATAR_IMAGE_MAX_EDGE).toBe(256);
    expect(containedImageSize(4032, 3024, AVATAR_IMAGE_MAX_EDGE)).toEqual({
      width: 256,
      height: 192,
    });
  });

  it('fits an image inside the requested edge without enlarging it', () => {
    expect(containedImageSize(4032, 3024, 1600)).toEqual({ width: 1600, height: 1200 });
    expect(containedImageSize(300, 200, 480)).toEqual({ width: 300, height: 200 });
  });

  it('derives immutable variants while leaving legacy URLs alone', () => {
    const display = 'https://storage.example/photos/u/123/display.webp';
    expect(imageVariantUrl(display, 'thumb')).toBe('https://storage.example/photos/u/123/thumb.webp');
    expect(imageVariantUrl(display, 'original', true)).toBe(
      'https://storage.example/photos/u/123/original?download=dice-photo-original',
    );
    expect(imageVariantUrl('https://storage.example/photos/legacy.jpg', 'thumb')).toBe(
      'https://storage.example/photos/legacy.jpg',
    );
  });

  it('rejects unsupported or oversized originals before decoding', async () => {
    await expect(compactImage(
      new File(['gif'], 'animated.gif', { type: 'image/gif' }),
      { maxEdge: 480 },
    )).rejects.toThrow('Use a JPEG, PNG, or WebP image.');

    const oversized = new File(
      [new Uint8Array(MAX_ORIGINAL_IMAGE_BYTES + 1)],
      'large.jpg',
      { type: 'image/jpeg' },
    );
    await expect(compactImage(oversized, { maxEdge: 480 })).rejects.toThrow(
      'Image must be 10 MB or smaller.',
    );
  });
});
