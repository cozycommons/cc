import { contentSecurityPolicies, credentialPage } from './csp.js';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const config = readFileSync(resolve(process.cwd(), 'nginx.conf'), 'utf8');

describe('production nginx SPA routing', () => {
  it('serves exact files without treating public directories as app routes', () => {
    expect(config).toMatch(/location \/ \{[\s\S]*?try_files \$uri @spa;/);
  });

  it('keeps the design system on the React SPA route', () => {
    expect(config).not.toContain('location ^~ /design/ {');
    expect(config).not.toContain('return 302 /design/;');
    expect(config).toMatch(/location \/ \{[\s\S]*?try_files \$uri @spa;/);
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
    expect(immutable).not.toMatch(/add_header Cache-Control[^;]*always/);
  });
});

describe('enforced CSP', () => {
  const policies = contentSecurityPolicies('https://api.example.test', 'https://auth.example.test');
  it('uses the normalized original route and retains headers in caching locations', () => {
    expect(config).toContain('map $uri $route_csp');
    expect(config).toContain('~*^/(account|oauth/consent)(/|$)');
    expect(config).toContain('set $document_csp $route_csp;');
    expect(config).toContain('try_files /index.html =404;');
    for (const location of config.matchAll(/location [^{]+\{([^}]+)\}/g)) {
      if (location[1].includes('add_header')) expect(location[1]).toContain('add_header Content-Security-Policy $document_csp always;');
    }
    expect(config).not.toContain('Content-Security-Policy-Report-Only');
  });
  it('normalizes trailing separators without widening credential destinations', () => {
    expect(contentSecurityPolicies('https://api.example.test///', 'https://auth.example.test/')).toEqual(policies);
  });
  it('blocks script injection, eval, frames, objects, forms and base changes', () => {
    for (const policy of Object.values(policies)) {
      for (const directive of ["default-src 'self'", "script-src 'self'", "object-src 'none'", "frame-ancestors 'none'", "frame-src 'none'", "form-action 'none'", "base-uri 'none'"]) expect(policy).toContain(directive);
      expect(policy).not.toContain('unsafe-eval');
      expect(policy).not.toMatch(/script-src[^;]*unsafe-inline/);
    }
  });
  it('allows both Google font artifact paths only on general pages', () => {
    expect(policies.general).toContain("font-src 'self' https://fonts.gstatic.com/s/ https://fonts.gstatic.com/l/font;");
    expect(policies.credentials).toContain("font-src 'self';");
  });
  it('excludes public images, gist, REST, realtime and upload origins from credentials', () => {
    expect(policies.credentials).not.toMatch(/https: |gist|rest\/v1|realtime|r2\.cloudflarestorage/);
    expect(policies.credentials).toContain('connect-src https://api.example.test/account https://api.example.test/account/ https://auth.example.test/auth/v1/ https://auth.example.test/storage/v1/');
    expect(policies.general).toContain('wss://auth.example.test/realtime/v1/');
    const withMedia = contentSecurityPolicies('https://api.example.test', 'https://auth.example.test', 'https://upload.example.test');
    expect(withMedia.general).toContain("media-src 'self' blob: https://upload.example.test");
    expect(withMedia.credentials).not.toContain('https://upload.example.test');
  });
  it.each(['https://user:pass@api.example.test', 'https://api.example.test/; img-src *', 'https://api.example.test/?x=1', 'http://external.example.test', 'https://api.example.test/$document_csp'])('rejects invalid service configuration %s', value => {
    expect(() => contentSecurityPolicies(value, 'https://auth.example.test')).toThrow();
  });
  it.each(['/account', '/ACCOUNT/', '/%61ccount', '/oauth/consent', '/OAuth/Consent///'])('protects React route spelling %s', path => expect(credentialPage(path)).toBe(true));
});

describe('security headers survive nginx add_header inheritance', () => {
  // A location with any add_header drops every server-level add_header, so each must repeat them.
  const blocks = [...config.matchAll(/location[^{]*\{([^}]*)\}/g)].map(m => m[1]).filter(b => b.includes('add_header'));
  it.each(blocks.map((b, i) => [i, b]))('location %i repeats CSP, nosniff and Referrer-Policy', (_, block) => {
    expect(block).toContain('add_header Content-Security-Policy $document_csp always;');
    expect(block).toContain('add_header X-Content-Type-Options nosniff always;');
    expect(block).toContain('add_header Referrer-Policy strict-origin-when-cross-origin always;');
  });
});
