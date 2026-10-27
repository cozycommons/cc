import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createInitialScene } from './initialScene';
import { localDraftKey, useFloorPlanDocument } from './useFloorPlanDocument';

vi.mock('../api.js', () => ({ getUrl: () => 'http://api.local' }));

const user = { id: 'owner-1', email: 'owner@example.test' };
const supabase = { auth: { getSession: vi.fn(async () => ({ data: { session: { user, access_token: 'test-token' } }, error: null })) } };
const plan = (id, revision = 1, scene = createInitialScene()) => ({ id, title: `Plan ${id}`, visibility: 'private', template: 'apartment', revision, scene, viewport: {}, can_edit: true, is_owner: true });
const response = (value, status = 200) => ({ ok: status < 400, status, json: async () => value });

describe('useFloorPlanDocument', () => {
  beforeEach(() => { window.localStorage.clear(); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers(); });

  it('switches plan IDs without carrying scene or recovery data across plans', async () => {
    const first = createInitialScene();
    const second = { ...createInitialScene(), title: 'Second plan', elements: [] };
    vi.stubGlobal('fetch', vi.fn(async (url) => response(url.endsWith('/one') ? plan('one', 1, first) : plan('two', 1, second))));
    const { result, rerender } = renderHook(({ id }) => useFloorPlanDocument(id, supabase, user), { initialProps: { id: 'one' } });
    await waitFor(() => expect(result.current.status).toBe('saved'));
    expect(result.current.scene.elements).toHaveLength(first.elements.length);
    rerender({ id: 'two' });
    await waitFor(() => expect(result.current.document.id).toBe('two'));
    expect(result.current.scene.elements).toEqual([]);
    expect(window.localStorage.getItem(localDraftKey(user.id, 'one'))).toBeNull();
  });

  it('keeps one revision save in flight, queues later edits, and writes a recovery draft immediately', async () => {
    let finishFirst;
    const fetchMock = vi.fn((url, options) => {
      if (options.method === 'GET') return Promise.resolve(response(plan('plan-1')));
      const payload = JSON.parse(options.body);
      if (fetchMock.mock.calls.filter(([, call]) => call.method === 'PATCH').length === 1) {
        return new Promise((resolve) => { finishFirst = () => resolve(response({ ...plan('plan-1', 2, payload.scene) })); });
      }
      return Promise.resolve(response({ ...plan('plan-1', 3, payload.scene) }));
    });
    vi.stubGlobal('fetch', fetchMock);
    const { result } = renderHook(() => useFloorPlanDocument('plan-1', supabase, user));
    await waitFor(() => expect(result.current.status).toBe('saved'));
    const firstScene = { ...result.current.scene, elements: [...result.current.scene.elements, { id: 'line-one', type: 'line', x1: 0, y1: 0, x2: 10, y2: 10 }] };
    act(() => result.current.setScene(firstScene));
    const savedDraft = JSON.parse(window.localStorage.getItem(localDraftKey(user.id, 'plan-1')));
    expect(savedDraft.scene.elements).toHaveLength(firstScene.elements.length);
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 700)); });
    expect(fetchMock.mock.calls.filter(([, call]) => call.method === 'PATCH')).toHaveLength(1);
    const secondScene = { ...firstScene, elements: [...firstScene.elements, { id: 'line-two', type: 'line', x1: 2, y1: 2, x2: 12, y2: 12 }] };
    act(() => result.current.setScene(secondScene));
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 700)); });
    expect(fetchMock.mock.calls.filter(([, call]) => call.method === 'PATCH')).toHaveLength(1);
    await act(async () => { finishFirst(); await Promise.resolve(); await Promise.resolve(); });
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 700)); });
    const patches = fetchMock.mock.calls.filter(([, call]) => call.method === 'PATCH');
    expect(patches).toHaveLength(2);
    expect(JSON.parse(patches[1][1].body).expected_revision).toBe(2);
    expect(JSON.parse(patches[1][1].body).scene.elements).toHaveLength(secondScene.elements.length);
    await waitFor(() => expect(result.current.status).toBe('saved'));
    expect(window.localStorage.getItem(localDraftKey(user.id, 'plan-1'))).toBeNull();
  });
});
