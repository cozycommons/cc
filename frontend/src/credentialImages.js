import { credentialPage } from '../csp.js';

// Product pages support arbitrary profile URLs. Credential pages use the
// generated local avatar when a remote image is outside their policy.
export function credentialImage(value, pathname = window.location.pathname) {
  if (!value || !credentialPage(pathname)) return value;
  try {
    const url = new URL(value, window.location.origin);
    const storage = new URL(import.meta.env.VITE_SUPABASE_URL);
    return url.origin === window.location.origin
      || (url.origin === storage.origin && url.pathname.startsWith(`${storage.pathname.replace(/\/$/, '')}/storage/v1/`))
      || url.origin === 'https://lh3.googleusercontent.com' ? value : null;
  } catch { return null; }
}
