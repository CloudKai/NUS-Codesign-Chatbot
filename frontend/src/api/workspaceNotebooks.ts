/** Owner-fenced notebook-list resource with confirmed-write reconciliation. */
import type { QueryClient } from '@tanstack/react-query';
import type { Notebook, NotebookList } from '../api';
import { readNotebookList } from './client';
import { ApiError } from './errors';
import { queryKeys } from './queryKeys';

/**
 * Reads stay immediately stale (every read verifies against the server), while
 * the last confirmed listing stays in memory only so a confirmed write has a
 * resource to reconcile into. Nothing enters persistent browser storage.
 */
export const notebooksPolicies = { staleTime: 0, gcTime: 300_000 } as const;

/** Query options for one owner's sidebar listing; the bootstrap result seeds this resource. */
export function notebooksQueryOptions(owner: string) {
  return {
    queryKey: queryKeys.notebooks(owner),
    staleTime: notebooksPolicies.staleTime,
    gcTime: notebooksPolicies.gcTime,
  };
}

/** Read the verified owner's sidebar listing and reject any answer for another owner. */
export async function fetchConfirmedNotebooks(owner: string, signal: AbortSignal): Promise<NotebookList> {
  const list = await readNotebookList(signal);
  if (list.owner_id !== owner) throw new ApiError(401);
  return list;
}

/** Seed the owner-verified bootstrap listing so the resource exists before the first write. */
export function seedNotebooks(client: QueryClient, owner: string, value: NotebookList): void {
  const cache = client.getQueryCache();
  const query = cache.build(client, { ...notebooksQueryOptions(owner), queryKey: queryKeys.notebooks(owner) });
  query.setData(value);
}

/** Insert a confirmed entry (newest first) or replace it, keeping every other identity. */
export function withEntry(list: NotebookList, entry: Notebook): NotebookList {
  const known = list.notebooks.some(item => item.id === entry.id);
  return { ...list, notebooks: known
    ? list.notebooks.map(item => item.id === entry.id ? entry : item)
    : [entry, ...list.notebooks] };
}

/** Remove one confirmed entry and only that entry's bounded preview. */
export function withoutEntry(list: NotebookList, id: string): NotebookList {
  const chat_summaries = { ...list.chat_summaries };
  delete chat_summaries[id];
  return { ...list, notebooks: list.notebooks.filter(item => item.id !== id), chat_summaries };
}

/**
 * Cancel reads that started before a write, then write the confirmed result so a
 * late pre-write response can never roll it back. Without cached data there is
 * nothing to reconcile; the caller's explicit list refresh stays authoritative.
 */
export async function reconcileNotebooks(
  client: QueryClient, owner: string, update: (list: NotebookList) => NotebookList,
): Promise<void> {
  await client.cancelQueries({ queryKey: queryKeys.notebooks(owner) });
  const cached = client.getQueryData<NotebookList>(queryKeys.notebooks(owner));
  if (cached && cached.owner_id === owner) client.setQueryData(queryKeys.notebooks(owner), update(cached));
}
