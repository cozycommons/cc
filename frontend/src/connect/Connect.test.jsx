import React from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, expect, it, vi } from 'vitest';
import Connect, { connectorUrl } from './Connect.jsx';

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const open = () => render(<MemoryRouter><Connect /></MemoryRouter>);
it('renders signed out with client instructions, permissions and disconnect guidance', () => {
  open();
  expect(screen.getByRole('heading', { name: 'Connect your agent' })).toBeInTheDocument();
  for (const client of ['Claude', 'ChatGPT', 'Muse', 'Grok', 'Other MCP clients']) expect(screen.getByText(client)).toBeInTheDocument();
  expect(screen.getByText('list_projects')).toBeInTheDocument();
  expect(screen.getAllByText('commons:edit').length).toBeGreaterThan(0);
  expect(screen.getByText('enable_project')).toBeInTheDocument();
  expect(screen.getByText('trips:edit')).toBeInTheDocument();
  expect(screen.getByRole('heading', { name: 'Connected before projects could be switched on?' })).toBeInTheDocument();
  expect(screen.getByRole('heading', { name: 'Disconnect' })).toBeInTheDocument();
  expect(screen.getByRole('link', { name: 'Floor Planner' })).toHaveAttribute('href', '/floor-planner');
  expect(screen.getByText('link_beli_account')).toBeInTheDocument();
  expect(screen.getByText('link_resy_account')).toBeInTheDocument();
  expect(screen.getByText('link_partiful_account')).toBeInTheDocument();
  expect(screen.getByText('link_espn_account')).toBeInTheDocument();
});
it('copies the connector URL and confirms success', async () => {
  const writeText = vi.fn().mockResolvedValue();
  vi.stubGlobal('navigator', { clipboard: { writeText } });
  open();
  fireEvent.click(screen.getByRole('button', { name: 'Copy' }));
  expect(await screen.findByRole('button', { name: 'Copied' })).toBeInTheDocument();
  expect(writeText).toHaveBeenCalledWith(screen.getByRole('textbox', { name: 'Connector URL' }).value);
  expect(screen.getByRole('status')).toHaveTextContent('Copied');
});
it('falls back to browser copy when clipboard permission is denied', async () => {
  vi.stubGlobal('navigator', { clipboard: { writeText: vi.fn().mockRejectedValue(new Error('denied')) } });
  Object.defineProperty(document, 'execCommand', { configurable: true, value: vi.fn(() => true) });
  open();
  fireEvent.click(screen.getByRole('button', { name: 'Copy' }));
  expect(await screen.findByRole('button', { name: 'Copied' })).toBeInTheDocument();
  expect(document.execCommand).toHaveBeenCalledWith('copy');
  delete document.execCommand;
});
it('selects the URL for manual copy when clipboard APIs are unavailable', async () => {
  vi.stubGlobal('navigator', {});
  open();
  fireEvent.click(screen.getByRole('button', { name: 'Copy' }));
  expect(await screen.findByText(/URL selected/)).toBeInTheDocument();
  const input = screen.getByRole('textbox', { name: 'Connector URL' });
  expect(input).toHaveFocus();
  expect(input.selectionEnd - input.selectionStart).toBe(input.value.length);
});
it('derives a public API origin and never advertises a loopback connector', () => {
  expect(connectorUrl('https://api.example.com/base')).toBe('https://api.example.com/mcp');
  for (const value of [undefined, '', 'bad', 'http://localhost:8000', 'https://localhost', 'https://a.localhost', 'https://127.0.0.1', 'https://[::1]', 'https://0.0.0.0', 'https://user:pass@api.example.com']) {
    expect(connectorUrl(value)).toBe('https://api.cozycommons.dev/mcp');
  }
});
