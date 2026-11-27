/** Owner-fenced, revision-aware bookmark resource with confirmed-write reconciliation. */
import type { QueryClient } from '@tanstack/react-query';
import type { Bookmarks } from '../api';
import { readBookmarks } from './client';
import { ApiError } from './errors';
import { queryKeys } from './queryKeys';

/**
 * Reads stay immediately stale (every read verifies against the server and the
 * live conversation revision), while the last confirmed projection stays in
 * memory only so a confirmed write has a resource to reconcile into. Nothing
 * enters persistent browser storage.
 */
export const bookmarksPolicies = { staleTime: 0, gcTime: 300_000 } as const;

/** Query options for one owner's bookmark projection in one notebook. */
export function bookmarksQueryOptions(owner: string, thread: string) {
  return {
    queryKey: queryKeys.bookmarks(owner, thread),
    staleTime: bookmarksPolicies.staleTime,
    gcTime: bookmarksPolicies.gcTime,
  };
}

/** Read the verified owner's bookmarks and reject any answer for another owner or notebook. */
export async function fetchConfirmedBookmarks(owner: string, thread: string, signal: AbortSignal): Promise<Bookmarks> {
  const value = await readBookmarks(thread, signal);
  if (value.owner_id !== owner || value.thread_id !== thread) throw new ApiError(401);
  return value;
}

/** Seed the verified workspace open read's bookmark projection. */
export function seedBookmarks(client: QueryClient, owner: string, thread: string, value: Bookmarks): void {
  const cache = client.getQueryCache();
  const query = cache.build(client, { ...bookmarksQueryOptions(owner, thread) });
  query.setData(value);
}

/**
 * Cancel reads that started before a write, then write the confirmed projection
 * so a late pre-write response can never roll it back. Without cached data
 * there is nothing to reconcile; the caller's explicit re-read stays
 * authoritative.
 */
export async function reconcileBookmarks(
  client: QueryClient, owner: string, thread: string, update: (value: Bookmarks) => Bookmarks,
): Promise<void> {
  await client.cancelQueries({ queryKey: queryKeys.bookmarks(owner, thread) });
  const cached = client.getQueryData<Bookmarks>(queryKeys.bookmarks(owner, thread));
  if (cached && cached.owner_id === owner) client.setQueryData(queryKeys.bookmarks(owner, thread), update(cached));
}
