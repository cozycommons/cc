import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const config = readFileSync(resolve(process.cwd(), 'nginx.conf'), 'utf8');

describe('production nginx SPA routing', () => {
  it('serves exact files without treating public directories as app routes', () => {
    expect(config).toMatch(/location \/ \{[\s\S]*?try_files \$uri \/index\.html;/);
  });

  it('exposes the static design comparison while preserving the Dice design route', () => {
    expect(config).toContain('location = /design {');
    expect(config).toContain('return 302 /design/;');
    expect(config).toContain('location = /design/dice {');
    expect(config).toContain('location ^~ /design/ {');
    expect(config).toContain('try_files $uri $uri/ =404;');
  });
});
