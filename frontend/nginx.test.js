import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const config = readFileSync(resolve(process.cwd(), 'nginx.conf'), 'utf8');

describe('production nginx SPA routing', () => {
  it('serves exact files without treating public directories as app routes', () => {
    expect(config).toMatch(/location \/ \{[\s\S]*?try_files \$uri \/index\.html;/);
  });

  it('keeps the design system on the React SPA route', () => {
    expect(config).not.toContain('location ^~ /design/ {');
    expect(config).not.toContain('return 302 /design/;');
    expect(config).toMatch(/location \/ \{[\s\S]*?try_files \$uri \/index\.html;/);
  });
});

describe('immutable asset scope', () => {
  const pattern = config.match(/location ~ "([^"]+)"/)[1];
  const hashedAsset = new RegExp(pattern);
  it.each(['index-AbcD_123.js', 'index-a1B2c3D4.css', 'font-abcdefgh.woff2', 'logo-12345678.svg'])(
    'caches hashed asset %s', file => expect(hashedAsset.test(`/assets/${file}`)).toBe(true),
  );
  it.each(['index.html', 'sw.js', 'sw-12345678.js', 'service-worker-12345678.js', 'sw-12345678.js.map', 'manifest.json', 'manifest-12345678.webmanifest', 'page-12345678.html', 'app.js', 'style.css', 'logo.svg'])(
    'does not cache unhashed or document asset %s immutably', file => expect(hashedAsset.test(`/assets/${file}`)).toBe(false),
  );
  it('serves missing and unhashed assets exactly with no SPA fallback', () => {
    expect(config).not.toContain('location ^~ /assets/');
    const unhashed = config.match(/location \/assets\/ \{([^}]+)\}/)[1];
    expect(unhashed).toContain('try_files $uri =404;');
    expect(unhashed).toContain('"no-cache" always');
    expect(unhashed).not.toContain('immutable');
    const immutable = config.match(/location ~ "[^"]+" \{([^}]+)\}/)[1];
    expect(immutable).toContain('try_files $uri =404;');
    expect(immutable).not.toContain('always');
  });
});
