/** Authenticate the full aggregate before exposing any private projection. */
import { afterEach, expect, it, vi } from 'vitest';
import { verifiedBootstrap } from '../api';
import { browserClient } from './client';
import { ApiError } from './errors';

const session = { owner_id: 'a', kind: 'guest', display_name: 'Student' };
const prefs = { owner_id: 'a', appearance: 'System', display_name: '', reduce_motion: false, default_mode: 'improve', starter_prompts: true };
const bootstrap = { session, listing: { owner_id: 'a', notebooks: [], chat_summaries: {} }, preferences: prefs };
afterEach(() => vi.unstubAllGlobals());

function responses(...values: (unknown | Error)[]) {
  browserClient.setConfig({ baseUrl: 'https://app.test' });
  const fetch = vi.fn();
  for (const value of values) {
    if (value instanceof Error) fetch.mockRejectedValueOnce(value);
    else fetch.mockResolvedValueOnce(Response.json(value));
  }
  vi.stubGlobal('fetch', fetch);
  return fetch;
}

it('uses bootstrap plus a fresh session probe before returning private views', async () => {
  const fetch = responses(bootstrap, session);
  expect(await verifiedBootstrap(new AbortController().signal)).toEqual(bootstrap);
  expect(fetch.mock.calls.map(([request]) => new URL(request.url).pathname)).toEqual([
    '/api/v1/reader/bootstrap', '/api/v1/reader/session',
  ]);
});

it.each(['session', 'listing', 'preferences'] as const)('rejects an owner mismatch in %s', async field => {
  const value = { ...bootstrap, [field]: { ...bootstrap[field], owner_id: 'foreign' } };
  responses(value, session);
  await expect(verifiedBootstrap(new AbortController().signal)).rejects.toEqual(new ApiError(401));
});

it('rejects a changed cookie identity after the aggregate read', async () => {
  responses(bootstrap, { ...session, owner_id: 'b' });
  await expect(verifiedBootstrap(new AbortController().signal)).rejects.toEqual(new ApiError(401));
});

it('never retries an aborted bootstrap', async () => {
  const abort = new DOMException('Aborted', 'AbortError');
  const fetch = responses(abort);
  await expect(verifiedBootstrap(new AbortController().signal)).rejects.toBe(abort);
  expect(fetch).toHaveBeenCalledTimes(1);
});

it('renews an expired registered cookie through the existing auth probe before retrying the read', async () => {
  browserClient.setConfig({ baseUrl: 'https://app.test' });
  const fetch = vi.fn()
    .mockResolvedValueOnce(Response.json({ detail: 'Expired' }, { status: 401 }))
    .mockResolvedValueOnce(Response.json({ detail: 'Expired' }, { status: 401 }))
    .mockResolvedValueOnce(Response.json({ user: { streamlit_access: false } }))
    .mockResolvedValueOnce(Response.json(session))
    .mockResolvedValueOnce(Response.json(bootstrap))
    .mockResolvedValueOnce(Response.json(session));
  vi.stubGlobal('fetch', fetch);
  expect(await verifiedBootstrap(new AbortController().signal)).toEqual(bootstrap);
  expect(fetch).toHaveBeenCalledTimes(6);
  expect(fetch.mock.calls[2][0]).toBe('/api/v1/auth/me');
});
