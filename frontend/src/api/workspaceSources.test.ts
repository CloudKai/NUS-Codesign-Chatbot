/** Owner-fenced source-catalog and upload-receipt resources: confirmed-write reconciliation. */
import { afterEach, expect, it, vi } from 'vitest';
import { createReaderQueryClient } from './queryClient';
import { queryKeys } from './queryKeys';
import { fetchConfirmedSources, fetchConfirmedUploads, reconcileSources, seedSources, sourcesPolicies } from './workspaceSources';
import { browserClient } from './client';
import { ApiError } from './errors';
import type { SourceList } from '../api';

const catalog: SourceList = { owner_id: 'a', thread_id: 't1', max_files: 5, max_file_bytes: 1024,
  sources: [{ id: 's1', title: 'Field notes', selected: false, locked: false, kind: 'file', size: 1024 }] };

afterEach(() => vi.unstubAllGlobals());

it('keeps source reads immediately stale while retaining the last confirmed catalog', () => {
  expect(sourcesPolicies.staleTime).toBe(0);
  expect(sourcesPolicies.gcTime).toBeGreaterThan(0);
});

it('rejects a catalog answered for another owner or notebook', async () => {
  browserClient.setConfig({ baseUrl: 'https://app.test' });
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(Response.json(catalog))));
  await expect(fetchConfirmedSources('a', 't2', new AbortController().signal)).rejects.toEqual(new ApiError(401));
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(Response.json({ ...catalog, owner_id: 'foreign' }))));
  await expect(fetchConfirmedSources('a', 't1', new AbortController().signal)).rejects.toEqual(new ApiError(401));
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(Response.json({ ...catalog, thread_id: 't2' }))));
  await expect(fetchConfirmedUploads('a', 't1', new AbortController().signal)).rejects.toEqual(new ApiError(401));
});

it('reconciles a confirmed catalog and cancels superseded list reads', async () => {
  const client = createReaderQueryClient();
  seedSources(client, 'a', 't1', catalog);
  let resolve!: (value: SourceList) => void;
  const pending = client.fetchQuery({ queryKey: queryKeys.sources('a', 't1'),
    queryFn: () => new Promise<SourceList>(done => { resolve = done; }) }).catch(() => undefined);
  const confirmed: SourceList = { ...catalog, sources: [{ ...catalog.sources[0], selected: true }] };
  await reconcileSources(client, 'a', 't1', () => confirmed);
  resolve(catalog); // A pre-write read finishing late must not roll back the confirmed catalog.
  await pending;
  expect(client.getQueryData(queryKeys.sources('a', 't1'))).toEqual(confirmed);
  client.clear();
});

it('never writes a confirmed catalog into another owner resource', async () => {
  const client = createReaderQueryClient();
  seedSources(client, 'b', 't1', catalog);
  await reconcileSources(client, 'a', 't1', () => ({ ...catalog, sources: [] }));
  expect(client.getQueryData(queryKeys.sources('b', 't1'))).toEqual(catalog);
  expect(client.getQueryData(queryKeys.sources('a', 't1'))).toBeUndefined();
  client.clear();
});
