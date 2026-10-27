import { render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import EditorCanvas from './EditorCanvas';

it('keeps the saved 2D viewport when returning from a scan, and fits only on request', () => {
  const setScene = vi.fn();
  const scene = { version: 2, units: 'inches', elements: [], viewport: { x: 47, y: 83, zoom: 2 } };
  const props = { scene, setScene, tool: 'select', setTool: vi.fn(), selectedId: null, setSelectedId: vi.fn(), onDeleteSelected: vi.fn(), onTransactionStart: vi.fn(), onTransactionEnd: vi.fn() };
  const view = render(<EditorCanvas {...props} fitSignal={0} />);
  expect(screen.getByLabelText('Floor plan drawing canvas').querySelector('g')).toHaveAttribute('transform', 'translate(47 83) scale(2)');
  expect(setScene).not.toHaveBeenCalled();
  view.rerender(<EditorCanvas {...props} fitSignal={1} />);
  expect(setScene).toHaveBeenCalledOnce();
});
