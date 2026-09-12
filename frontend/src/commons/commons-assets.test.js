import { describe, expect, it } from 'vitest';
import {
  getCommonsActorAnimation,
  getCommonsAsset,
  getCommonsHitbox,
  getCommonsRenderMetadata,
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

  it('exposes a consistent four-direction resident walk atlas', () => {
    expect(getCommonsActorAnimation('host')).toMatchObject({
      path: '/commons/assets/resident-host-walk.svg',
      frameWidth: 64,
      frameHeight: 96,
      frames: 16,
    });
    expect(getCommonsActorAnimation('maker')?.path).toBe('/commons/assets/resident-maker-walk.svg');
    expect(getCommonsActorAnimation('neighbor')?.path).toBe('/commons/assets/resident-neighbor-walk.svg');
  });

  it('keeps interaction zones on the visible base of props and actors', () => {
    expect(getCommonsHitbox('orange-sofa')).toMatchObject({ y: 0.58, height: 0.34 });
    expect(getCommonsHitbox('host', 'actor')).toMatchObject({ y: 0.58, height: 0.38 });
  });

  it('exposes stable logical render metadata for grounded sizing', () => {
    expect(getCommonsRenderMetadata('orange-sofa')).toMatchObject({ width: 200, depthOffset: 0 });
    expect(getCommonsRenderMetadata('host')).toMatchObject({ width: 30, height: 46, depthOffset: 0 });
    expect(getCommonsRenderMetadata('area-rug')).toMatchObject({ floorDecoration: true, depthOffset: -900 });
    expect(getCommonsRenderMetadata('unknown')).toMatchObject({ width: 82, anchor: [0.5, 1] });
  });
});
