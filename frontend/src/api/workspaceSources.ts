/** Owner-fenced source-catalog and upload-receipt resources with confirmed-write reconciliation. */
import type { QueryClient } from '@tanstack/react-query';
import type { SourceList, UploadJobs } from '../api';
import { readSources, readUploads } from './client';
import { ApiError } from './errors';
import { queryKeys } from './queryKeys';

/**
 * Reads stay immediately stale (every read verifies against the server, and
 * upload receipts change between polls), while the last confirmed catalog and
 * receipts stay in memory only so a confirmed write has a resource to
 * reconcile into. Nothing enters persistent browser storage.
 */
export const sourcesPolicies = { staleTime: 0, gcTime: 300_000 } as const;

/** Query options for one owner's catalog in one notebook or the private Library. */
export function sourcesQueryOptions(owner: string, thread: string) {
  return {
    queryKey: queryKeys.sources(owner, thread),
    staleTime: sourcesPolicies.staleTime,
    gcTime: sourcesPolicies.gcTime,
  };
}

/** Query options for one owner's bounded upload receipts in one notebook. */
export function uploadsQueryOptions(owner: string, thread: string) {
  return {
    queryKey: queryKeys.uploads(owner, thread),
    staleTime: sourcesPolicies.staleTime,
    gcTime: sourcesPolicies.gcTime,
  };
}

/** Read the verified owner's source catalog and reject any answer for another owner or notebook. */
export async function fetchConfirmedSources(owner: string, thread: string, signal: AbortSignal): Promise<SourceList> {
  const list = await readSources(thread, signal);
  if (list.owner_id !== owner || list.thread_id !== thread) throw new ApiError(401);
  return list;
}

/** Read one notebook's upload receipts and reject any answer for another owner or notebook. */
export async function fetchConfirmedUploads(owner: string, thread: string, signal: AbortSignal): Promise<UploadJobs> {
  const value = await readUploads(thread, signal);
  if (value.owner_id !== owner || value.thread_id !== thread) throw new ApiError(401);
  return value;
}

/** Seed the last confirmed catalog so a confirmed write has a resource to reconcile into. */
export function seedSources(client: QueryClient, owner: string, thread: string, value: SourceList): void {
  const cache = client.getQueryCache();
  const query = cache.build(client, { ...sourcesQueryOptions(owner, thread) });
  query.setData(value);
}

/** Seed the last confirmed upload receipts. */
export function seedUploads(client: QueryClient, owner: string, thread: string, value: UploadJobs): void {
  const cache = client.getQueryCache();
  const query = cache.build(client, { ...uploadsQueryOptions(owner, thread) });
  query.setData(value);
}

/**
 * Cancel reads that started before a write, then write the confirmed catalog so
 * a late pre-write response can never roll it back. Without cached data there
 * is nothing to reconcile; the caller's explicit refresh stays authoritative.
 */
export async function reconcileSources(
  client: QueryClient, owner: string, thread: string, update: (list: SourceList) => SourceList,
): Promise<void> {
  await client.cancelQueries({ queryKey: queryKeys.sources(owner, thread) });
  const cached = client.getQueryData<SourceList>(queryKeys.sources(owner, thread));
  if (cached && cached.owner_id === owner) client.setQueryData(queryKeys.sources(owner, thread), update(cached));
}
