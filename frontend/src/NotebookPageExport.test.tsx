/**
 * @vitest-environment jsdom
 */
/** The notebook page export control selects saved work and downloads through the public route. */
import { afterEach, beforeAll, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { NotebookPage } from './NotebookPage';
import { browserClient } from './api/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const notebook = { id: 'n1', name: 'Market project', parent_notebook_id: null } as never;

function listResponse(path: string) {
  if (path.endsWith('/artifacts')) {
    return Response.json({ artifacts: [
      { id: 'a1', title: 'Field notes', kind: 'notes', updated_at: '2026-11-26T00:00:00Z' },
      { id: 'a2', title: 'Concept draft', kind: 'notes', updated_at: '2026-11-26T00:00:00Z' },
    ], kinds: ['notes'] });
  }
  if (path.endsWith('/canvases')) {
    return Response.json({ canvases: [
      { id: 'c1', title: 'Crossing map', updated_at: '2026-11-26T00:00:00Z' },
    ] });
  }
  return Response.json({ exported: true });
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

/** jsdom has no blob URL store; the download only needs the methods to exist. */
beforeAll(() => {
  Object.assign(URL, { createObjectURL: vi.fn(() => 'blob:test'), revokeObjectURL: vi.fn() });
});

it('moves left through notebook tabs and wraps from Chats to Export', () => {
  vi.stubGlobal('fetch', vi.fn(async () => Response.json({ canvases: [], artifacts: [], kinds: ['notes'] })));
  render(<QueryClientProvider client={new QueryClient()}><NotebookPage notebook={notebook} entries={[]} summaries={{}} owner="a"
    locked={false} expired={vi.fn()} createChat={vi.fn()} openChat={vi.fn()}
    openArtifact={vi.fn()} createArtifact={vi.fn()} openCanvas={vi.fn()}/></QueryClientProvider>);
  fireEvent.keyDown(screen.getByRole('tab', { name: 'Chats' }), { key: 'ArrowLeft' });
  expect(screen.getByRole('tab', { name: 'Export' }).getAttribute('aria-selected')).toBe('true');
  expect(document.activeElement).toBe(screen.getByRole('tab', { name: 'Export' }));
  fireEvent.keyDown(screen.getByRole('tab', { name: 'Export' }), { key: 'ArrowLeft' });
  expect(screen.getByRole('tab', { name: 'Sources' }).getAttribute('aria-selected')).toBe('true');
});

it('downloads only the selected artifacts and canvases from the notebook page', async () => {
  browserClient.setConfig({ baseUrl: 'https://app.test' });
  const fetch = vi.fn((request: Request | string, init?: RequestInit) => {
    const url = typeof request === 'string' ? request : request.url;
    const path = new URL(url, 'https://app.test').pathname;
    void init;
    return Promise.resolve(listResponse(path));
  });
  vi.stubGlobal('fetch', fetch);
  render(<NotebookPage notebook={notebook} entries={[]} summaries={{}} owner="a"
    locked={false} expired={vi.fn()} createChat={vi.fn()} openChat={vi.fn()}
    openArtifact={vi.fn()} createArtifact={vi.fn()} openCanvas={vi.fn()}/>);

  fireEvent.click(screen.getByRole('tab', { name: 'Export' }));
  const includeFieldNotes = await screen.findByRole('checkbox', { name: 'Include Field notes' });
  const includeCanvas = await screen.findByRole('checkbox', { name: 'Include Crossing map' });
  fireEvent.click(includeFieldNotes);
  fireEvent.click(includeCanvas);

  fireEvent.click(screen.getByRole('button', { name: 'Download project export' }));
  await waitFor(() => expect(fetch.mock.calls.some(([url]) => String(url).includes('/project/export'))).toBe(true));
  const request = fetch.mock.calls.find(([url]) => String(url).includes('/project/export'))!;
  const url = new URL(String(request[0]), 'https://app.test');
  expect(url.pathname).toBe('/api/v1/reader/threads/n1/project/export');
  expect(url.searchParams.get('artifacts')).toBe('a1');
  expect(url.searchParams.get('canvases')).toBe('c1');
  expect((request[1] as RequestInit).credentials).toBe('same-origin');
  expect((request[1] as RequestInit).cache).toBe('no-store');
  await waitFor(() => expect(screen.getByText('Project export downloaded.')).toBeTruthy());
});
