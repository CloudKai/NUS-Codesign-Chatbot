/** Owner-fenced, revision-aware bookmark resource: confirmed-write reconciliation and identity races. */
import { afterEach, expect, it, vi } from 'vitest';
import { createReaderQueryClient } from './queryClient';
import { queryKeys } from './queryKeys';
import { fetchConfirmedBookmarks, bookmarksPolicies, reconcileBookmarks, seedBookmarks } from './workspaceBookmarks';
import { browserClient } from './client';
import { ApiError } from './errors';
import type { Bookmarks } from '../api';

const saved: Bookmarks = { owner_id: 'a', thread_id: 't1', conversation_revision: 3, messages: [
  { id: 'm1', role: 'user', preview: 'My reasoning', stage_id: 'framing', interaction_intent: null } ] };

afterEach(() => vi.unstubAllGlobals());

it('keeps bookmark reads immediately stale while retaining the last confirmed projection', () => {
  expect(bookmarksPolicies.staleTime).toBe(0);
  expect(bookmarksPolicies.gcTime).toBeGreaterThan(0);
});

it('rejects a bookmark answer for another owner or notebook', async () => {
  browserClient.setConfig({ baseUrl: 'https://app.test' });
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(Response.json({ ...saved, owner_id: 'foreign' }))));
  await expect(fetchConfirmedBookmarks('a', 't1', new AbortController().signal)).rejects.toEqual(new ApiError(401));
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(Response.json({ ...saved, thread_id: 't2' }))));
  await expect(fetchConfirmedBookmarks('a', 't1', new AbortController().signal)).rejects.toEqual(new ApiError(401));
});

it('reconciles a confirmed bookmark projection and cancels superseded reads', async () => {
  const client = createReaderQueryClient();
  seedBookmarks(client, 'a', 't1', saved);
  let resolve!: (value: Bookmarks) => void;
  const pending = client.fetchQuery({ queryKey: queryKeys.bookmarks('a', 't1'),
    queryFn: () => new Promise<Bookmarks>(done => { resolve = done; }) }).catch(() => undefined);
  const starred: Bookmarks = { ...saved, messages: [...saved.messages,
    { id: 'm2', role: 'assistant', preview: 'Coach answer', stage_id: 'ideation', interaction_intent: 'project_coaching' } ] };
  await reconcileBookmarks(client, 'a', 't1', () => starred);
  resolve(saved); // A pre-write read finishing late must not roll back the confirmed projection.
  await pending;
  expect(client.getQueryData(queryKeys.bookmarks('a', 't1'))).toEqual(starred);
  client.clear();
});

it('never writes a confirmed projection into another owner resource', async () => {
  const client = createReaderQueryClient();
  seedBookmarks(client, 'b', 't1', saved);
  await reconcileBookmarks(client, 'a', 't1', () => ({ ...saved, messages: [] }));
  expect(client.getQueryData(queryKeys.bookmarks('b', 't1'))).toEqual(saved);
  expect(client.getQueryData(queryKeys.bookmarks('a', 't1'))).toBeUndefined();
  client.clear();
});
