import { DICE_SAME_ORIGIN } from '../sandboxConstants.js';

export function resolveRuntimeServiceUrl(configuredUrl, browserOrigin = window.location.origin) {
  if (configuredUrl !== DICE_SAME_ORIGIN) return configuredUrl;

  const origin = new URL(browserOrigin);
  if (!['http:', 'https:'].includes(origin.protocol) || origin.origin !== browserOrigin) {
    throw new Error('Dice same-origin sandbox requires a valid browser origin');
  }
  return origin.origin;
}
