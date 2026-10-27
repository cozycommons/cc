import { getUrl } from '../api';

export const MAX_SCAN_BYTES = 50 * 1024 * 1024;

export async function scanRequest(supabase, userId, planId, { method = 'GET', file, scanId, content = false, signal } = {}) {
  const { data, error } = await supabase.auth.getSession();
  if (error) throw error;
  if (!userId || data.session?.user?.id !== userId) throw new Error('Your account changed. Reload this plan.');
  const query = new URLSearchParams();
  if (file) query.set('filename', file.name);
  if (scanId) query.set('expected_id', scanId);
  const suffix = content ? '/content' : '';
  const response = await fetch(`${getUrl()}/floor-planner/plans/${encodeURIComponent(planId)}/scan${suffix}?${query}`, {
    method, signal, cache: 'no-store',
    headers: { Authorization: `Bearer ${data.session.access_token}`, ...(file ? { 'Content-Type': 'model/vnd.usdz+zip' } : {}) },
    ...(file ? { body: file } : {}),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const failure = new Error(body.detail || `Scan request failed (${response.status}).`);
    failure.status = response.status;
    throw failure;
  }
  if (response.status === 204) return null;
  if (content) return response.arrayBuffer();
  return response.json();
}
