import { describe, expect, it } from 'vitest';
import {
  getCommonsActorAnimation,
  getCommonsAsset,
  shouldMirrorCommonsAsset,
} from './commons-assets.js';

describe('Commons furniture assets', () => {
  it('selects dedicated north-facing sprites when available', () => {
    expect(getCommonsAsset('green-loveseat', 'north')).toBe('/commons/assets/green-loveseat-north.png');
    expect(shouldMirrorCommonsAsset('green-loveseat', 'north')).toBe(false);
  });

  it('uses a deterministic mirror fallback for remaining asymmetric furniture', () => {
    expect(getCommonsAsset('record-console', 'north')).toBe('/commons/assets/record-console.png');
    expect(shouldMirrorCommonsAsset('record-console', 'north')).toBe(true);
  });

  it('keeps the original sprite as the default orientation', () => {
    expect(getCommonsAsset('orange-sofa')).toBe('/commons/assets/orange-sofa.png');
    expect(shouldMirrorCommonsAsset('orange-sofa')).toBe(false);
  });

  it('exposes a consistent four-frame host walk strip', () => {
    expect(getCommonsActorAnimation('host')).toMatchObject({
      path: '/commons/assets/host-walk.png',
      frameWidth: 444,
      frameHeight: 889,
      frames: 4,
    });
    expect(getCommonsActorAnimation('maker')?.path).toBe('/commons/assets/maker-walk.png');
    expect(getCommonsActorAnimation('neighbor')?.path).toBe('/commons/assets/neighbor-walk.png');
  });
});
