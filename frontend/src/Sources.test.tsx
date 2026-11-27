/**
 * @vitest-environment jsdom
 */
/** Observed source selection through the generated contract and resource reconciliation. */
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import { Sources } from './Sources';
import { createReaderQueryClient } from './api/queryClient';
import { queryKeys } from './api/queryKeys';
import { browserClient } from './api/client';
import type { SourceList } from './api';

const session = { owner_id: 'a', kind: 'registered', display_name: 'Student' };
const catalog: SourceList = { owner_id: 'a', thread_id: 't1', max_files: 5, max_file_bytes: 1024,
  sources: [{ id: 's1', title: 'Field notes', selected: false, locked: false, kind: 'file', size: 1024 }] };

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('saves a selection through the generated contract and reconciles the source resource', async () => {
  browserClient.setConfig({ baseUrl: 'https://app.test' });
  const confirmed: SourceList = { ...catalog, sources: [{ ...catalog.sources[0], selected: true }] };
  let saved = false;
  const fetch = vi.fn((request: Request) => {
    const path = new URL(request.url).pathname;
    if (path === '/api/v1/reader/session') return Promise.resolve(Response.json(session));
    if (request.method === 'POST') {
      saved = true;
      return Promise.resolve(Response.json(confirmed));
    }
    if (path.endsWith('/uploads')) {
      return Promise.resolve(Response.json({ owner_id: 'a', thread_id: 't1', jobs: [] }));
    }
    // After the confirmed write the server keeps the saved selection.
    return Promise.resolve(Response.json(saved ? confirmed : catalog));
  });
  vi.stubGlobal('fetch', fetch);
  const client = createReaderQueryClient();
  render(<QueryClientProvider client={client}>
    <Sources owner="a" thread="t1" disabled={false} expired={vi.fn()} embedded/>
  </QueryClientProvider>);
  const checkbox = await screen.findByRole('checkbox', { name: 'Use Field notes in answers' });
  fireEvent.click(checkbox);
  await waitFor(() => expect(screen.getAllByText('Source selection saved.').length).toBeGreaterThan(0));
  const request = (fetch.mock.calls.find(([sent]) => (sent as Request).method === 'POST'))![0] as Request;
  expect(new URL(request.url).pathname).toBe('/api/v1/reader/threads/t1/sources/s1/select');
  expect(await request.text()).toBe(JSON.stringify({ selected: true }));
  await waitFor(() => expect(client.getQueryData(queryKeys.sources('a', 't1'))).toEqual(confirmed));
  expect((screen.getByRole('checkbox', { name: 'Use Field notes in answers' }) as HTMLInputElement).checked).toBe(true);
});
