// Keep build-time origins and the browser's credential-page boundary in one module.
export function credentialPage(pathname) {
  let decoded;
  try { decoded = decodeURIComponent(pathname); } catch { return false; }
  return /^\/(account|oauth\/consent)(\/|$)/i.test(decoded);
}

export function serviceUrl(value) {
  const url = new URL(value);
  const loopback = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
  if ((url.protocol !== 'https:' && !(loopback && url.protocol === 'http:')) || url.username || url.password
      || url.search || url.hash || /[\s;"'\\${}]/.test(value)) {
    throw new Error('CSP service URLs require HTTPS (HTTP only on loopback), without credentials, query or fragment');
  }
  return url.href.replace(/\/+$/, '');
}

export function contentSecurityPolicies(apiValue, supabaseValue, uploadValue = '') {
  const api = serviceUrl(apiValue), supabase = serviceUrl(supabaseValue);
  const websocket = supabase.replace(/^http/, 'ws');
  const upload = uploadValue ? new URL(serviceUrl(uploadValue)).origin : '';
  const common = "default-src 'self'; script-src 'self'; script-src-attr 'none'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; frame-src 'none'; form-action 'none'; worker-src 'none'; manifest-src 'self'";
  return {
    general: `${common}; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com/css2; font-src 'self' https://fonts.gstatic.com/s/; connect-src 'self' ${new URL(api).origin} ${supabase}/auth/v1/ ${supabase}/rest/v1/ ${supabase}/storage/v1/ ${websocket}/realtime/v1/ https://gist.githubusercontent.com/homatthew/a417a860db31c1a9e5c13b08338b7a65/raw/ ${upload}; img-src 'self' https: data: blob:; media-src 'self' blob: ${upload}`,
    credentials: `${common}; style-src 'self' 'unsafe-inline'; font-src 'self'; connect-src ${api}/account ${api}/account/ ${supabase}/auth/v1/ ${supabase}/storage/v1/; img-src 'self' data: blob: ${supabase}/storage/v1/ https://lh3.googleusercontent.com; media-src 'none'`,
  };
}
