import { readdir, stat } from 'node:fs/promises';
import path from 'node:path';

const assetsDirectory = path.resolve('dist/assets');
const maximumChunkBytes = 500 * 1024;
const files = (await readdir(assetsDirectory)).filter((file) => file.endsWith('.js'));
const sizes = await Promise.all(files.map(async (file) => ({
  file,
  bytes: (await stat(path.join(assetsDirectory, file))).size,
})));
const oversized = sizes.filter(({ bytes }) => bytes > maximumChunkBytes);

if (oversized.length > 0) {
  for (const { file, bytes } of oversized) {
    console.error(`${file} is ${(bytes / 1024).toFixed(1)} KiB (limit: 500 KiB)`);
  }
  process.exit(1);
}

console.log(`Bundle budget passed: ${files.length} JavaScript chunks, each at most 500 KiB.`);
