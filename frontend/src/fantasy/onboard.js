// Login-based ESPN onboarding. The password goes to the backend once,
// over HTTPS, and is never stored — here or there (see docs/espn.md).
export async function onboardWithLogin(apiUrl, payload) {
  const response = await fetch(`${apiUrl}/espn/onboard/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw Object.assign(new Error(body?.detail || `HTTP ${response.status}`), {
      status: response.status,
      detail: body?.detail,
    });
  }
  return body;
}
