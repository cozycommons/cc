import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import FloorPlannerApp, { TOOLS } from './App';
import { createInitialScene } from './initialScene';
import { listFloorPlanInvitations } from './useFloorPlanDocument';

let editorState;
const user = { id: 'person-1', email: 'person@example.test' };
const supabase = {};
const signIn = vi.fn();
vi.mock('./ScanPanel', () => ({ default: () => <section aria-label="Attached scan" /> }));
vi.mock('./useFloorPlanDocument', () => ({
  usePlannerAuth: () => ({ supabase, user, loading: false, signIn }),
  useFloorPlanDocument: () => editorState,
  listFloorPlanInvitations: vi.fn().mockResolvedValue([]),
}));

function renderEditor() {
  return render(<MemoryRouter initialEntries={['/floor-planner/plans/plan-1']}><Routes><Route path="/floor-planner/*" element={<FloorPlannerApp />} /></Routes></MemoryRouter>);
}

describe('FloorPlannerApp', () => {
  beforeEach(() => {
    const scene = createInitialScene();
    editorState = { scene, setScene: vi.fn(), document: { id: 'plan-1', title: 'Apartment plan', template: 'apartment', visibility: 'private', revision: 1 }, status: 'saved', message: 'Saved to cloud', canEdit: true, isOwner: true, draftAvailable: false, restoreDraft: vi.fn(), discardDraft: vi.fn() };
    signIn.mockClear();
    listFloorPlanInvitations.mockClear();
  });

  afterEach(() => {
    delete HTMLDialogElement.prototype.showModal;
  });

  it('keeps the measured apartment and editor tools intact', () => {
    renderEditor();
    expect(screen.getByRole('heading', { name: 'Apartment plan' })).toBeInTheDocument();
    expect(screen.getByLabelText('Floor plan drawing canvas')).toBeInTheDocument();
    TOOLS.forEach(([, label]) => expect(screen.getByRole('button', { name: label })).toBeInTheDocument());
    expect(editorState.scene.elements.filter((item) => item.type === 'wall')).toHaveLength(56);
    expect(editorState.scene.elements.filter((item) => item.type === 'opening' && item.kind === 'door')).toHaveLength(14);
    expect(editorState.scene.elements.filter((item) => item.type === 'opening' && item.kind === 'window')).toHaveLength(2);
  });

  it('switches tools and retains precision snap affordance', () => {
    renderEditor();
    fireEvent.click(screen.getByRole('button', { name: 'Wall' }));
    expect(screen.getByRole('button', { name: 'Wall' })).toHaveClass('active');
    expect(screen.getByText(/2″ snap/)).toBeInTheDocument();
  });

  it('does not handle hidden 2D undo shortcuts while viewing a scan', () => {
    renderEditor();
    fireEvent.click(screen.getByRole('tab', { name: '3D scan' }));
    expect(screen.getByRole('button', { name: 'Undo' })).toBeDisabled();
    const event = new KeyboardEvent('keydown', { key: 'z', ctrlKey: true, bubbles: true, cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(false);
    expect(editorState.setScene).not.toHaveBeenCalled();
  });

  it('omits public presence identity/count and exposes sharing only to the owner', () => {
    renderEditor();
    expect(screen.getByRole('button', { name: 'Share' })).toBeInTheDocument();
    expect(screen.queryByText(/here$/)).not.toBeInTheDocument();
  });

  it('opens the sharing dialog with the invite form and empty invitation state', async () => {
    const showModal = vi.fn(function () { this.setAttribute('open', ''); });
    Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value: showModal });
    renderEditor();

    fireEvent.click(screen.getByRole('button', { name: 'Share' }));

    const dialog = await screen.findByRole('dialog', { name: 'Share Apartment plan' });
    expect(showModal).toHaveBeenCalledOnce();
    expect(screen.getByLabelText('Invite by email')).toBeInTheDocument();
    expect(screen.getByText('No invitations yet.')).toBeInTheDocument();
    await waitFor(() => expect(listFloorPlanInvitations).toHaveBeenCalledWith(supabase, user.id, 'plan-1'));
    expect(dialog).toBeVisible();
  });

  it('keeps the drawing editable and recovery controls visible after save failure', () => {
    editorState = { ...editorState, status: 'conflict', message: 'This plan changed elsewhere. Your local draft is still available.', draftAvailable: true };
    renderEditor();
    expect(screen.getByLabelText('Floor plan drawing canvas')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Recover local draft' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reload latest' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Wall' })).toBeEnabled();
  });

  it('shows view-only canvas controls without owner sharing for public plans', () => {
    editorState = { ...editorState, canEdit: false, isOwner: false, document: { ...editorState.document, visibility: 'public' }, message: 'Public read-only' };
    renderEditor();
    expect(screen.getByText('Public read-only')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Share' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Wall' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Hand' })).toBeEnabled();
  });
});
