import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const config = readFileSync(resolve(process.cwd(), 'nginx.conf'), 'utf8');

describe('production nginx SPA routing', () => {
  it('serves exact files without treating public directories as app routes', () => {
    expect(config).toContain('try_files $uri /index.html;');
    expect(config).not.toMatch(/try_files[^;]*\$uri\//);
  });
});
