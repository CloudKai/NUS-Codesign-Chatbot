/** Owner-fenced, revision-aware project resource with confirmed-write reconciliation. */
import type { QueryClient } from '@tanstack/react-query';
import type { Project } from '../api';
import { readProject } from './client';
import { ApiError } from './errors';
import { queryKeys } from './queryKeys';

/**
 * Reads stay immediately stale (every read re-verifies saved stage authority),
 * while the last confirmed projection stays in memory only so a confirmed
 * decision has a resource to reconcile into. Nothing enters persistent browser
 * storage, and no decision is ever applied optimistically.
 */
export const projectPolicies = { staleTime: 0, gcTime: 300_000 } as const;

/** Query options for one owner's project projection in one notebook. */
export function projectQueryOptions(owner: string, thread: string) {
  return {
    queryKey: queryKeys.project(owner, thread),
    staleTime: projectPolicies.staleTime,
    gcTime: projectPolicies.gcTime,
  };
}

/** Read the verified owner's project and reject any answer for another owner or notebook. */
export async function fetchConfirmedProject(owner: string, thread: string, signal: AbortSignal): Promise<Project> {
  const value = await readProject(thread, signal);
  if (value.owner_id !== owner || value.thread_id !== thread) throw new ApiError(401);
  return value;
}

/** Seed the verified workspace open read's project projection. */
export function seedProject(client: QueryClient, owner: string, thread: string, value: Project): void {
  const cache = client.getQueryCache();
  const query = cache.build(client, { ...projectQueryOptions(owner, thread) });
  query.setData(value);
}

/**
 * Cancel reads that started before a decision, then write the confirmed
 * projection so a late pre-write response can never roll it back. Without
 * cached data there is nothing to reconcile; the caller's authoritative
 * refresh stays responsible for the visible state.
 */
export async function reconcileProject(
  client: QueryClient, owner: string, thread: string, update: (value: Project) => Project,
): Promise<void> {
  await client.cancelQueries({ queryKey: queryKeys.project(owner, thread) });
  const cached = client.getQueryData<Project>(queryKeys.project(owner, thread));
  if (cached && cached.owner_id === owner) client.setQueryData(queryKeys.project(owner, thread), update(cached));
}
