import React from 'react';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { Field, Form, Modal } from './ui.jsx';

const nativeShow = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, 'showModal');
const nativeClose = Object.getOwnPropertyDescriptor(HTMLDialogElement.prototype, 'close');
beforeEach(() => {
  Object.defineProperty(HTMLDialogElement.prototype, 'showModal', { configurable: true, value() { this.open = true; } });
  Object.defineProperty(HTMLDialogElement.prototype, 'close', { configurable: true, value() { this.open = false; } });
});
afterEach(() => {
  cleanup(); vi.restoreAllMocks();
  if (nativeShow) Object.defineProperty(HTMLDialogElement.prototype, 'showModal', nativeShow);
  else delete HTMLDialogElement.prototype.showModal;
  if (nativeClose) Object.defineProperty(HTMLDialogElement.prototype, 'close', nativeClose);
  else delete HTMLDialogElement.prototype.close;
});

function open(onSubmit, onClose) {
  render(<Modal title="Expense" onClose={onClose}><Form submit="Save expense" onSubmit={onSubmit} onCancel={onClose}>
    <Field label="Description"><input defaultValue="Dinner" /></Field>
  </Form></Modal>);
  const dialog = screen.getByRole('dialog');
  vi.spyOn(dialog, 'getBoundingClientRect').mockReturnValue({ left: 20, right: 320, top: 20, bottom: 420 });
  return dialog;
}

it('keeps a pending save in its original dialog through every dismissal path', async () => {
  let finish;
  const pending = new Promise(resolve => { finish = resolve; });
  const close = vi.fn();
  const dialog = open(() => pending, close);
  fireEvent.click(screen.getByRole('button', { name: 'Save expense' }));
  expect(dialog).toHaveAttribute('aria-busy', 'true');
  expect(screen.getByRole('button', { name: 'Close dialog' })).toBeDisabled();
  expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'Close dialog' }));
  fireEvent(dialog, new Event('cancel', { bubbles: true, cancelable: true }));
  fireEvent.click(dialog, { clientX: 2, clientY: 2 });
  expect(close).not.toHaveBeenCalled();
  expect(screen.getByLabelText('Description')).toHaveValue('Dinner');
  await act(async () => { finish(); await pending; });
  expect(screen.getByRole('button', { name: 'Close dialog' })).toBeEnabled();
  fireEvent.click(screen.getByRole('button', { name: 'Close dialog' }));
  expect(close).toHaveBeenCalledOnce();
});

it('keeps padding clicks inside the dialog and permits a real backdrop dismissal', () => {
  const close = vi.fn();
  const dialog = open(vi.fn(), close);
  fireEvent.click(dialog, { clientX: 25, clientY: 25 });
  expect(close).not.toHaveBeenCalled();
  fireEvent.click(dialog, { clientX: 2, clientY: 2 });
  expect(close).toHaveBeenCalledOnce();
});

it('retains a failed draft and enables closing after the failure', async () => {
  const close = vi.fn();
  open(() => Promise.reject(new Error('Connection interrupted')), close);
  fireEvent.click(screen.getByRole('button', { name: 'Save expense' }));
  expect(await screen.findByRole('alert')).toHaveTextContent('Connection interrupted');
  expect(screen.getByLabelText('Description')).toHaveValue('Dinner');
  expect(screen.getByRole('button', { name: 'Close dialog' })).toBeEnabled();
});
