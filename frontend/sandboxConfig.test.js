import { describe, expect, it } from 'vitest'
import { resolveCodespacesSandbox } from './sandboxConfig.js'

describe('resolveCodespacesSandbox', () => {
  it('returns no sandbox outside Codespaces', () => {
    expect(resolveCodespacesSandbox({})).toBeNull()
  })

  it('derives the one allowed forwarded origin from GitHub metadata', () => {
    expect(resolveCodespacesSandbox({
      CODESPACES: 'true',
      CODESPACE_NAME: 'friendly-space',
      GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN: 'app.github.dev',
    })).toEqual({
      host: 'friendly-space-8080.app.github.dev',
      origin: 'https://friendly-space-8080.app.github.dev',
    })
  })

  it.each([
    { CODESPACE_NAME: '../escape', GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN: 'app.github.dev' },
    { CODESPACE_NAME: 'friendly-space', GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN: 'https://app.github.dev' },
    { CODESPACE_NAME: 'friendly-space', GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN: 'app.github.dev:443' },
  ])('rejects invalid host metadata: %o', (metadata) => {
    expect(() => resolveCodespacesSandbox({
      CODESPACES: 'true',
      ...metadata,
    })).toThrow('valid GitHub Codespaces host metadata')
  })
})
