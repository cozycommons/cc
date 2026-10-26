import { beforeEach, describe, expect, it, vi } from 'vitest';
import { projectForPath, sessionForActivity, trackEvent } from './events.js';
vi.mock('../supabase.js', () => ({ getClient: () => ({ auth: { getSession: async () => ({ data: { session: null } }) } }) }));
vi.mock('../api.js', () => ({ getUrl: () => 'http://127.0.0.1:8000' }));
beforeEach(() => { localStorage.clear(); vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true })); });
describe('shared telemetry', () => {
  it('tracks product routes only', () => {
    expect(projectForPath('/')).toBe('commons'); expect(projectForPath('/dice/stats')).toBe('dice');
    expect(projectForPath('/trips/123')).toBe('trips'); expect(projectForPath('/crowdset/show')).toBe('crowdset');
    expect(projectForPath('/admin')).toBeNull(); expect(projectForPath('/design/dice')).toBeNull(); expect(projectForPath('/dice-other')).toBeNull();
  });
  it('shares sessions until 30 minutes without activity', () => {
    const id = sessionForActivity(1000); expect(sessionForActivity(2000)).toBe(id);
    expect(sessionForActivity(2000 + 30 * 60 * 1000)).not.toBe(id);
  });
  it('sends an anonymous envelope without identity or URL queries', async () => {
    await trackEvent({ project: 'dice', eventType: 'pageview', eventName: 'dice.page_viewed', path: '/dice' });
    const [url, request] = fetch.mock.calls[0]; const body = JSON.parse(request.body);
    expect(url).toContain('/track/events'); expect(body.session_id).toBeTruthy(); expect(body.user_id).toBeUndefined(); expect(body.event_id).toBeTruthy();
  });
});
