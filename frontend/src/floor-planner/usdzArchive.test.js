import { afterEach, describe, expect, it, vi } from 'vitest';
import { zipSync } from 'three/addons/libs/fflate.module.js';
import { ArchiveOnlyComposer, parseScanArchive } from './usdzArchive';
import { SYNTHETIC_USDC_BASE64 } from './usdcFixture';

describe('self-contained USDZ parsing', () => {
  afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

  it('parses a nested ASCII USDZ root into real mesh geometry', async () => {
    const usd = '#usda 1.0\ndef Mesh "Wall" {\n point3f[] points = [(0,0,0), (3,0,0), (3,2,0), (0,2,0)]\n int[] faceVertexCounts = [4]\n int[] faceVertexIndices = [0,1,2,3]\n}\n';
    const zip = zipSync({ 'scan/root.usda': new Uint8Array([...usd].map((character) => character.charCodeAt(0))) });
    const model = await parseScanArchive(zip.buffer);
    let meshes = 0;
    model.traverse((object) => { if (object.isMesh) { meshes++; expect(object.geometry.attributes.position.count).toBeGreaterThan(0); } });
    expect(meshes).toBe(1);
  });

  it('rejects every URL texture before an Image can request external bytes', () => {
    const image = vi.fn();
    vi.stubGlobal('Image', image);
    const composer = new ArchiveOnlyComposer();
    for (const url of ['https://outside.example/room.png', '../room.png', 'scan/room.png', 'data:image/png;base64,abc']) {
      expect(() => composer._createTextureFromData(url)).toThrow('self-contained USDZ');
    }
    expect(image).not.toHaveBeenCalled();
  });

  it('parses a genuine binary USDC root without a server converter', async () => {
    const binary = Uint8Array.from(atob(SYNTHETIC_USDC_BASE64), (character) => character.charCodeAt(0));
    const zip = zipSync({ 'root.usdc': binary });
    const model = await parseScanArchive(zip.buffer);
    let meshes = 0;
    model.traverse((object) => { if (object.isMesh) { meshes++; expect(object.geometry.attributes.position.count).toBeGreaterThan(0); } });
    expect(meshes).toBe(1);
  });

  it('loads embedded image bytes through a local blob URL and releases it', async () => {
    const requested = [];
    vi.stubGlobal('Image', class { set src(value) { requested.push(value); this.onload(); } });
    const create = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:scan-image');
    const revoke = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {});
    const composer = new ArchiveOnlyComposer();
    composer._createTextureFromData(new Uint8Array([1, 2, 3]));
    await Promise.all(composer.texturePromises);
    expect(requested).toEqual(['blob:scan-image']);
    expect(create).toHaveBeenCalledOnce();
    expect(revoke).toHaveBeenCalledWith('blob:scan-image');
  });
});
