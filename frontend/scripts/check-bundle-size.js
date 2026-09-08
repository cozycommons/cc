import { readdir, stat } from 'node:fs/promises';
import path from 'node:path';

const assetsDirectory = path.resolve('dist/assets');
const maximumChunkBytes = 500 * 1024;
const maximumPhaserChunkBytes = 1600 * 1024;
const files = (await readdir(assetsDirectory)).filter((file) => file.endsWith('.js'));
const sizes = await Promise.all(files.map(async (file) => ({
  file,
  bytes: (await stat(path.join(assetsDirectory, file))).size,
})));
const oversized = sizes.filter(({ file, bytes }) => {
  const maximumBytes = file.startsWith('phaser-')
    ? maximumPhaserChunkBytes
    : maximumChunkBytes;
  return bytes > maximumBytes;
});

if (oversized.length > 0) {
  for (const { file, bytes } of oversized) {
    const limit = file.startsWith('phaser-') ? maximumPhaserChunkBytes : maximumChunkBytes;
    console.error(`${file} is ${(bytes / 1024).toFixed(1)} KiB (limit: ${limit / 1024} KiB)`);
  }
  process.exit(1);
}

console.log(
  `Bundle budget passed: ${files.length} JavaScript chunks; regular chunks are at most 500 KiB and the Phaser engine is at most 1600 KiB.`,
);
