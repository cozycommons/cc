import { useCallback, useEffect, useRef, useState } from 'react';
import { getUrl } from '../api.js';
import { useSupabase } from '../contexts/SupabaseContext';
import { SCENE_VERSION, createInitialScene } from './initialScene';

export function isValidScene(scene) {
  return scene?.version === SCENE_VERSION && scene.units === 'inches' && Array.isArray(scene.elements)
    && scene.elements.every((element) => typeof element?.id === 'string' && typeof element?.type === 'string');
}

export function blankScene() {
  return { version: SCENE_VERSION, title: 'Untitled plan', units: 'inches', rooms: [], elements: [], viewport: null };
}

export function localDraftKey(userId, planId) {
  return `floor-planner:draft:v1:${userId}:${planId}`;
}

async function request(supabase, path, method = 'GET', payload, expectedUserId) {
  const { data, error } = await supabase.auth.getSession();
  if (error) throw error;
  const session = data.session;
  if (expectedUserId && session?.user?.id !== expectedUserId) throw new Error('Your account changed. Reload this plan to continue.');
  const response = await fetch(`${getUrl()}/floor-planner${path}`, {
    method,
    cache: 'no-store',
    headers: { 'Content-Type': 'application/json', ...(session?.access_token ? { Authorization: `Bearer ${session.access_token}` } : {}) },
    ...(payload === undefined ? {} : { body: JSON.stringify(payload) }),
  });
  const body = response.status === 204 ? null : await response.json().catch(() => ({}));
  if (!response.ok) {
    const failure = new Error(body?.detail || `Floor Planner request failed (${response.status}).`);
    failure.status = response.status;
    throw failure;
  }
  return body;
}

export function usePlannerAuth() {
  const { supabase, auth } = useSupabase();
  const [state, setState] = useState({ loading: true, user: null });
  useEffect(() => {
    let active = true;
    let version = 0;
    const initialVersion = version;
    supabase.auth.getSession().then(({ data, error }) => {
      if (active && version === initialVersion) setState({ loading: false, user: error ? null : data.session?.user ?? null });
    }).catch(() => { if (active && version === initialVersion) setState({ loading: false, user: null }); });
    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      version += 1;
      if (active) setState({ loading: false, user: session?.user ?? null });
    });
    return () => { active = false; subscription.unsubscribe(); };
  }, [supabase]);
  return { ...state, supabase, signIn: () => auth.signInWithGoogle(`${window.location.origin}${window.location.pathname}${window.location.search}`) };
}

export function useFloorPlanDocument(planId, supabase, user) {
  const [scene, setSceneState] = useState(blankScene);
  const [document, setDocument] = useState(null);
  const [status, setStatus] = useState('loading');
  const [message, setMessage] = useState('Loading plan');
  const [canEdit, setCanEdit] = useState(false);
  const [isOwner, setIsOwner] = useState(false);
  const [draftAvailable, setDraftAvailable] = useState(false);
  const sceneRef = useRef(scene);
  const dirtyRef = useRef(false);
  const documentRef = useRef(document);
  const userId = user?.id ?? null;
  const generation = useRef(0);
  const saveInFlight = useRef(false);
  sceneRef.current = scene;
  documentRef.current = document;

  useEffect(() => {
    let active = true;
    const current = ++generation.current;
    dirtyRef.current = false;
    setSceneState(blankScene());
    setDocument(null);
    setCanEdit(false);
    setIsOwner(false);
    setDraftAvailable(false);
    setStatus('loading');
    setMessage('Loading plan');
    request(supabase, `/plans/${encodeURIComponent(planId)}`, 'GET', undefined, userId).then((loaded) => {
      if (!active || current !== generation.current) return;
      if (!isValidScene(loaded.scene)) throw new Error('This plan has an unsupported drawing format.');
      setDocument(loaded);
      documentRef.current = loaded;
      setCanEdit(loaded.can_edit);
      setIsOwner(loaded.is_owner);
      const viewport = loaded.viewport && ['x', 'y', 'zoom'].every((key) => Number.isFinite(loaded.viewport[key])) && loaded.viewport.zoom > 0
        ? loaded.viewport : loaded.scene.viewport ?? null;
      setSceneState({ ...loaded.scene, viewport });
      setStatus('saved');
      setMessage(loaded.can_edit ? 'Saved to cloud' : 'Public read-only');
      if (loaded.can_edit && userId) {
        try {
          const draft = JSON.parse(window.localStorage.getItem(localDraftKey(userId, planId)) || 'null');
          setDraftAvailable(isValidScene(draft?.scene));
        } catch { setDraftAvailable(false); }
      }
    }).catch((error) => {
      if (!active || current !== generation.current) return;
      let hasDraft = false;
      if (userId) {
        try {
          const draft = JSON.parse(window.localStorage.getItem(localDraftKey(userId, planId)) || 'null');
          if (isValidScene(draft?.scene)) { setSceneState(draft.scene); hasDraft = true; }
        } catch { /* Ignore corrupt recovery data. */ }
      }
      setDraftAvailable(hasDraft);
      setStatus(error.status === 403 || error.status === 404 ? 'access-error' : 'load-error');
      setMessage(hasDraft ? `${error.message} Your local draft is still available.` : error.message);
    });
    return () => { active = false; };
  }, [planId, supabase, userId]);

  const setScene = useCallback((update) => {
    const next = typeof update === 'function' ? update(sceneRef.current) : update;
    if (canEdit && isValidScene(next)) {
      dirtyRef.current = true;
      const activeDocument = documentRef.current;
      if (userId && activeDocument?.id) {
        try {
          window.localStorage.setItem(localDraftKey(userId, activeDocument.id), JSON.stringify({ scene: next, baseRevision: activeDocument.revision }));
          setDraftAvailable(true);
        } catch { /* Keep the in-memory edit even when storage is unavailable. */ }
      }
      if (!['conflict', 'revoked', 'error'].includes(status)) {
        setStatus('saving');
        setMessage('Unsaved changes');
      }
    }
    sceneRef.current = next;
    setSceneState(next);
  }, [canEdit, status, userId]);

  useEffect(() => {
    if (!canEdit || !userId || !document?.id || !dirtyRef.current) return undefined;
    const key = localDraftKey(userId, document.id);
    const timeout = window.setTimeout(async () => {
      if (saveInFlight.current) return;
      const submittedScene = sceneRef.current;
      try {
        window.localStorage.setItem(key, JSON.stringify({ scene: submittedScene, baseRevision: documentRef.current?.revision }));
        setDraftAvailable(true);
      } catch { /* Keep the in-memory edit even when storage is unavailable. */ }
      setStatus('saving');
      setMessage('Saving');
      saveInFlight.current = true;
      try {
        const saved = await request(supabase, `/plans/${encodeURIComponent(document.id)}`, 'PATCH', {
          expected_revision: documentRef.current.revision,
          scene: submittedScene,
        }, userId);
        if (documentRef.current?.id !== document.id || sceneRef.current !== submittedScene) {
          if (documentRef.current?.id === document.id) {
            documentRef.current = saved;
            setDocument(saved);
            setStatus('saving');
          }
          return;
        }
        documentRef.current = saved;
        setDocument(saved);
        dirtyRef.current = false;
        window.localStorage.removeItem(key);
        setDraftAvailable(false);
        setStatus('saved');
        setMessage('Saved to cloud');
      } catch (error) {
        if (documentRef.current?.id !== document.id) return;
        setStatus(error.status === 409 ? 'conflict' : error.status === 403 || error.status === 404 ? 'revoked' : 'error');
        if (error.status === 403 || error.status === 404) setCanEdit(false);
        setMessage(`${error.message} Your local draft is still available.`);
      } finally {
        saveInFlight.current = false;
      }
    }, 650);
    return () => window.clearTimeout(timeout);
  }, [canEdit, document?.id, document?.revision, scene, supabase, userId]);

  useEffect(() => {
    if (!supabase || !document?.id) return undefined;
    const timer = window.setInterval(async () => {
      try {
        const next = await request(supabase, `/plans/${encodeURIComponent(document.id)}`, 'GET', undefined, userId);
        if (documentRef.current?.id !== document.id) return;
        const current = documentRef.current;
        setCanEdit(next.can_edit);
        setIsOwner(next.is_owner);
        if (next.can_edit !== current?.can_edit) {
          documentRef.current = next;
          setDocument(next);
          if (dirtyRef.current && !next.can_edit) {
            setStatus('revoked');
            setMessage('Your edit access changed. Your local draft is still available.');
            return;
          }
          if (!dirtyRef.current) {
            setStatus('saved');
            setMessage(next.can_edit ? 'Edit access enabled' : 'Public read-only');
          }
        }
        if (next.revision <= (current?.revision ?? 0)) return;
        if (dirtyRef.current) {
          setStatus('conflict');
          setMessage('This plan changed elsewhere. Your local draft is still available.');
          return;
        }
        documentRef.current = next;
        setDocument(next);
        const viewport = next.viewport && ['x', 'y', 'zoom'].every((key) => Number.isFinite(next.viewport[key])) && next.viewport.zoom > 0
          ? next.viewport : next.scene.viewport ?? null;
        setSceneState({ ...next.scene, viewport });
        setMessage(next.can_edit ? 'Updated live' : 'Public plan · updated live');
      } catch (error) {
        if (documentRef.current?.id !== document.id || ![401, 403, 404].includes(error.status)) return;
        setCanEdit(false);
        if (!dirtyRef.current) {
          setStatus('revoked');
          setMessage('Plan access changed. This open copy is read-only.');
        } else {
          setStatus('revoked');
          setMessage('Plan access changed. Your local draft is still available.');
        }
      }
    }, 6000);
    return () => window.clearInterval(timer);
  }, [canEdit, document?.id, supabase, userId]);

  const restoreDraft = useCallback(() => {
    if (!userId || !document?.id || !canEdit) return;
    try {
      const draft = JSON.parse(window.localStorage.getItem(localDraftKey(userId, document.id)) || 'null');
      if (!isValidScene(draft?.scene)) return;
      setScene(draft.scene);
      setDraftAvailable(false);
      setMessage('Recovering local draft');
    } catch { setDraftAvailable(false); }
  }, [canEdit, document?.id, setScene, userId]);

  const discardDraft = useCallback(() => {
    if (!userId || !planId) return;
    window.localStorage.removeItem(localDraftKey(userId, planId));
    setDraftAvailable(false);
  }, [planId, userId]);

  return { scene, setScene, document, status, message, canEdit, isOwner, draftAvailable, restoreDraft, discardDraft };
}

export const listFloorPlans = (supabase, userId) => request(supabase, '/plans', 'GET', undefined, userId);
export const createFloorPlan = (supabase, userId, template, title) => request(supabase, '/plans', 'POST', { template, title, scene: template === 'apartment' ? createInitialScene() : blankScene() }, userId);
export const updateFloorPlan = (supabase, userId, id, expectedRevision, changes) => request(supabase, `/plans/${encodeURIComponent(id)}`, 'PATCH', { expected_revision: expectedRevision, ...changes }, userId);
export const deleteFloorPlan = (supabase, userId, id) => request(supabase, `/plans/${encodeURIComponent(id)}`, 'DELETE', undefined, userId);
export const listFloorPlanInvitations = (supabase, userId, id) => request(supabase, `/plans/${encodeURIComponent(id)}/invitations`, 'GET', undefined, userId);
export const addFloorPlanInvitation = (supabase, userId, id, email) => request(supabase, `/plans/${encodeURIComponent(id)}/invitations`, 'POST', { email }, userId);
export const revokeFloorPlanInvitation = (supabase, userId, id, invitationId) => request(supabase, `/plans/${encodeURIComponent(id)}/invitations/${encodeURIComponent(invitationId)}`, 'DELETE', undefined, userId);
