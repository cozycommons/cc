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
    console.error(`${file} is ${(bytes / 1024).toFixed(1)} KiB (limit: ${maximumChunkBytes / 1024} KiB)`);
  }
  process.exit(1);
}

console.log(
  `Bundle budget passed: ${files.length} JavaScript chunks; all chunks are at most 500 KiB.`,
);

// Follow static imports only. Dynamic route/auth imports are intentionally deferred.
// Include the tiny auth facade: Fantasy requests it on mount, even anonymously.
const { readFile } = await import('node:fs/promises');
const { gzipSync } = await import('node:zlib');
const manifest = JSON.parse(await readFile('dist/.vite/manifest.json', 'utf8'));
const closure = new Set();
function visit(key) {
  if (closure.has(key)) return;
  if (!manifest[key]) throw new Error(`Missing manifest entry: ${key}`);
  closure.add(key);
  for (const dependency of manifest[key].imports || []) visit(dependency);
}
for (const root of ['index.html', 'src/fantasy/Fantasy.jsx', 'src/fantasy/auth.js']) visit(root);
const forbidden = [...closure].filter(key => /supabase|src\/(dice|trips|crowdset|design)\/|\.\.\/design\//i.test(key));
if (forbidden.length) throw new Error(`Anonymous Fantasy imports deferred code: ${forbidden.join(', ')}`);
const initialFiles = new Set();
for (const key of closure) {
  initialFiles.add(manifest[key].file);
  for (const css of manifest[key].css || []) initialFiles.add(css);
}
const totals = { js: 0, css: 0 };
for (const file of initialFiles) {
  const extension = path.extname(file).slice(1);
  if (extension in totals) totals[extension] += gzipSync(await readFile(path.join('dist', file)), { level: 9 }).length;
}
// Keep headroom for small additions while catching an SDK or route-sized regression.
if (totals.js > 185 * 1024 || totals.css > 25 * 1024) {
  throw new Error(`Anonymous Fantasy gzip budget exceeded: ${JSON.stringify(totals)}`);
}
console.log(`Anonymous Fantasy static closure passed: gzip-9 JS ${totals.js} bytes; CSS ${totals.css} bytes.`);
