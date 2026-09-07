export const DICE_SANDBOX_PORT = 8080

const DNS_LABEL = /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/

function isDnsName(value) {
  return value
    .split('.')
    .every((label) => DNS_LABEL.test(label))
}

export function resolveCodespacesSandbox(env = process.env) {
  if (env.CODESPACES !== 'true') return null

  const name = env.CODESPACE_NAME || ''
  const forwardingDomain = env.GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN || ''
  if (!DNS_LABEL.test(name) || !isDnsName(forwardingDomain)) {
    throw new Error('Codespaces sandbox requires valid GitHub Codespaces host metadata')
  }

  const host = `${name}-${DICE_SANDBOX_PORT}.${forwardingDomain}`
  return {
    host,
    origin: `https://${host}`,
  }
}
