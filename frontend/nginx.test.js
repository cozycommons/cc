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
