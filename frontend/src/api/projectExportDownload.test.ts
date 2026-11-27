/**
 * @vitest-environment jsdom
 */
/** The selected project export keeps the same-origin, no-store, cancellation download policy. */
import { afterEach, expect, it, vi } from 'vitest';
import { browserClient, downloadProjectExport } from './client';

afterEach(() => vi.unstubAllGlobals());

it('downloads the selected project export with the existing download policy', async () => {
  browserClient.setConfig({ baseUrl: 'https://app.test' });
  const fetch = vi.fn((url: string, _init?: RequestInit) => {
    void url;
    return Promise.resolve(Response.json({ exported: true }));
  });
  vi.stubGlobal('fetch', fetch);
  const controller = new AbortController();
  await downloadProjectExport('t1', 'My project', ['a1', 'a2'], ['c1'], controller.signal);
  const requestUrl = String(fetch.mock.calls[0][0]);
  const init = (fetch.mock.calls[0] as unknown as [string, RequestInit])[1];
  const url = new URL(requestUrl, 'https://app.test');
  expect(url.pathname).toBe('/api/v1/reader/threads/t1/project/export');
  expect(url.searchParams.get('artifacts')).toBe('a1,a2');
  expect(url.searchParams.get('canvases')).toBe('c1');
  expect(init.credentials).toBe('same-origin');
  expect(init.cache).toBe('no-store');
  controller.abort();
  expect((init.signal as AbortSignal).aborted).toBe(true);
});
