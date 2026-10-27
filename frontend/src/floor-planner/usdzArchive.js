import { unzipSync } from 'three/addons/libs/fflate.module.js';
import { USDAParser } from 'three/addons/loaders/usd/USDAParser.js';
import { USDCParser } from 'three/addons/loaders/usd/USDCParser.js';
import { USDComposer } from 'three/addons/loaders/usd/USDComposer.js';

// Pinned Three.js also loads some image paths without consulting LoadingManager.
export class ArchiveOnlyComposer extends USDComposer {
  _createTextureFromData(data, ...options) {
    if (typeof data === 'string') throw new Error('The scan references an external file. Upload a self-contained USDZ.');
    return super._createTextureFromData(data, ...options);
  }
}

export async function parseScanArchive(bytes) {
  const zip = unzipSync(new Uint8Array(bytes));
  const assets = {}, layers = {};
  const ascii = new USDAParser(), binary = new USDCParser(), decoder = new TextDecoder();
  const rootName = Object.keys(zip)[0];
  if (!/\.(usd|usda|usdc)$/i.test(rootName || '')) throw new Error('The USDZ must start with a USD root layer.');
  for (const [name, data] of Object.entries(zip)) {
    if (/\.(usd|usda|usdc)$/i.test(name)) {
      const isBinary = decoder.decode(data.subarray(0, 8)) === 'PXR-USDC';
      assets[name] = isBinary ? binary.parseData(data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength)) : ascii.parseData(decoder.decode(data));
      layers[name] = assets[name];
    } else if (/\.(png|jpe?g|avif)$/i.test(name)) assets[name] = data;
  }
  const composer = new ArchiveOnlyComposer();
  const basePath = rootName.includes('/') ? rootName.slice(0, rootName.lastIndexOf('/')) : '';
  const model = composer.compose(layers[rootName], assets, {}, basePath);
  await Promise.all(composer.texturePromises);
  return model;
}
