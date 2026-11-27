/** Owner-fenced preference and notebook-settings Query resources with measured freshness. */
import { useMutation, useQuery, useQueryClient, type QueryClient, type UseMutationOptions } from '@tanstack/react-query';
import type { NotebookSettings, NotebookSettingsPatch, Preferences } from '../api';
import { readNotebookSettings, readPreferences, updateNotebookSettings, updatePreferences } from './client';
import { ApiError } from './errors';
import { queryKeys } from './queryKeys';

/**
 * Freshness and retention configured per resource, adopted only after the
 * identity-lifecycle tests (expiry, account switch, delayed response) pass.
 * Values sit inside the approved investigation ranges (preferences 1–2 minutes,
 * notebook settings 30 seconds); the global Query defaults remain zero, so each
 * resource opts in here. Positive retention is local synthetic evidence, not a
 * production capacity or correctness claim.
 */
export const resourcePolicies = {
  preferences: { staleTime: 90_000, gcTime: 300_000 },
  notebookSettings: { staleTime: 30_000, gcTime: 300_000 },
} as const;

/** Read preferences and reject any answer that does not belong to the verified owner. */
export async function fetchConfirmedPreferences(owner: string, signal: AbortSignal): Promise<Preferences> {
  const value = await readPreferences(signal);
  if (value.owner_id !== owner) throw new ApiError(401);
  return value;
}

/** Read one notebook's settings and reject foreign owners or mismatched notebooks. */
export async function fetchConfirmedNotebookSettings(owner: string, thread: string, signal: AbortSignal): Promise<NotebookSettings> {
  const value = await readNotebookSettings(thread, signal);
  if (value.owner_id !== owner || value.notebook.id !== thread) throw new ApiError(401);
  return value;
}

/** Query options for one owner's preferences; the bootstrap result seeds this resource. */
export function preferencesQueryOptions(owner: string) {
  return {
    queryKey: queryKeys.preferences(owner),
    staleTime: resourcePolicies.preferences.staleTime,
    gcTime: resourcePolicies.preferences.gcTime,
  };
}

/** Seed the verified bootstrap preferences so no component refetches them immediately. */
export function seedPreferences(client: QueryClient, owner: string, value: Preferences): void {
  client.setQueryData(queryKeys.preferences(owner), value);
}

/** Query options for one notebook's owner-fenced settings; a verified workspace read seeds this resource. */
export function notebookSettingsQueryOptions(owner: string, thread: string) {
  return {
    queryKey: queryKeys.notebookSettings(owner, thread),
    staleTime: resourcePolicies.notebookSettings.staleTime,
    gcTime: resourcePolicies.notebookSettings.gcTime,
  };
}

/** Seed one verified workspace read's settings so settings components never refetch immediately. */
export function seedNotebookSettings(client: QueryClient, owner: string, thread: string, value: NotebookSettings): void {
  const cache = client.getQueryCache();
  const query = cache.build(client, { ...notebookSettingsQueryOptions(owner, thread) });
  query.setData(value);
}

/** React resource for the verified owner's presentation defaults. */
export function usePreferences(owner: string) {
  return useQuery({ ...preferencesQueryOptions(owner),
    queryFn: ({ signal }) => fetchConfirmedPreferences(owner, signal) });
}

/** Mutation options that reconcile one confirmed save into the preferences resource only. */
export function preferencesMutationOptions(client: QueryClient, owner: string): UseMutationOptions<Preferences, unknown, { patch: Partial<Omit<Preferences, 'owner_id'>>; signal?: AbortSignal }> {
  return {
    mutationFn: ({ patch, signal }) => updatePreferences(patch, signal ?? new AbortController().signal),
    onSuccess: async (value, variables) => {
      if (value.owner_id !== owner) throw new ApiError(401);
      // A write reconciliation must not reuse a read that started before the write.
      await client.cancelQueries({ queryKey: queryKeys.preferences(owner) });
      client.setQueryData(queryKeys.preferences(owner), value);
      void variables;
    },
  };
}

/** React mutation saving preference keys and reconciling only the confirmed result. */
export function useSavePreferences(owner: string) {
  const client = useQueryClient();
  return useMutation(preferencesMutationOptions(client, owner));
}

/** React resource for one notebook's owner-fenced settings; disabled without a notebook. */
export function useNotebookSettings(owner: string, thread: string | undefined) {
  return useQuery({
    ...notebookSettingsQueryOptions(owner, thread ?? 'none'),
    enabled: thread !== undefined,
    queryFn: async ({ signal }) => {
      try { return await fetchConfirmedNotebookSettings(owner, thread ?? '', signal); }
      catch (error) {
        // A removed notebook resolves to "no settings" instead of failing the page.
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    },
  });
}

/** Mutation options that reconcile one confirmed settings save into that notebook only. */
export function notebookSettingsMutationOptions(client: QueryClient, owner: string, thread: string): UseMutationOptions<NotebookSettings, unknown, { patch: NotebookSettingsPatch; signal?: AbortSignal }> {
  return {
    mutationFn: ({ patch, signal }) => updateNotebookSettings(thread, patch, signal ?? new AbortController().signal),
    onSuccess: async value => {
      if (value.owner_id !== owner || value.notebook.id !== thread) throw new ApiError(401);
      await client.cancelQueries({ queryKey: queryKeys.notebookSettings(owner, thread) });
      client.setQueryData(queryKeys.notebookSettings(owner, thread), value);
    },
  };
}

/** React mutation saving notebook controls and reconciling only the confirmed result. */
export function useSaveNotebookSettings(owner: string, thread: string | undefined) {
  const client = useQueryClient();
  return useMutation(notebookSettingsMutationOptions(client, owner, thread ?? 'none'));
}
