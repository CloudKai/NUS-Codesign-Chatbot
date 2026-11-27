/** Owner-fenced preference and settings resources: reuse, identity races and measured freshness. */
import { afterEach, expect, it, vi } from 'vitest';
import { MutationObserver } from '@tanstack/react-query';
import { createReaderQueryClient } from './queryClient';
import { queryKeys } from './queryKeys';
import { fetchConfirmedPreferences, preferencesMutationOptions, preferencesQueryOptions,
  resourcePolicies, seedNotebookSettings, seedPreferences } from './workspaceSettings';
import { browserClient } from './client';
import { ApiError } from './errors';
import type { NotebookSettings, Preferences } from '../api';

const prefs: Preferences = { owner_id: 'a', appearance: 'Dark', display_name: 'Kai',
  reduce_motion: false, default_mode: 'project', starter_prompts: true };
const settingsFixture: NotebookSettings = { owner_id: 'a',
  notebook: { id: 't1', name: 'Studio', kind: 'notebook', pinned: false, parent_notebook_id: null },
  response_detail: 'short', response_language: 'English', selected_model: 'mock',
  reasoning_effort: null, assignment: {}, models: [], chat_model_label: 'Mock coach' };

afterEach(() => vi.unstubAllGlobals());

function reply(...values: unknown[]) {
  browserClient.setConfig({ baseUrl: 'https://app.test' });
  const fetch = vi.fn();
  for (const value of values) fetch.mockResolvedValueOnce(Response.json(value));
  vi.stubGlobal('fetch', fetch);
  return fetch;
}

it('scopes preference and settings keys to one verified owner and notebook', () => {
  expect(queryKeys.preferences('a')).not.toEqual(queryKeys.preferences('b'));
  expect(queryKeys.notebookSettings('a', 't1')).not.toEqual(queryKeys.notebookSettings('a', 't2'));
  expect(queryKeys.notebookSettings('a', 't1')).not.toEqual(queryKeys.notebookSettings('b', 't1'));
});

it('configures resource freshness separately from the zero-retention global defaults', () => {
  expect(resourcePolicies.preferences.staleTime).toBeGreaterThan(0);
  expect(resourcePolicies.preferences.gcTime).toBeGreaterThan(0);
  expect(resourcePolicies.notebookSettings).not.toEqual(resourcePolicies.preferences);
});

it('reuses owner-verified bootstrap preferences without an immediate duplicate read', async () => {
  const client = createReaderQueryClient();
  seedPreferences(client, 'a', prefs);
  const fetch = vi.fn(() => Promise.resolve(prefs));
  const value = await client.fetchQuery({
    ...preferencesQueryOptions('a'), queryFn: fetch,
  });
  expect(value).toEqual(prefs);
  expect(fetch).not.toHaveBeenCalled();
  client.clear();
});

it('reuses a verified workspace read so settings components never refetch immediately', async () => {
  const client = createReaderQueryClient();
  seedNotebookSettings(client, 'a', 't1', settingsFixture);
  const fetch = vi.fn(() => Promise.resolve(settingsFixture));
  const value = await client.fetchQuery({
    queryKey: queryKeys.notebookSettings('a', 't1'),
    staleTime: resourcePolicies.notebookSettings.staleTime,
    gcTime: resourcePolicies.notebookSettings.gcTime,
    queryFn: fetch,
  });
  expect(value).toEqual(settingsFixture);
  expect(fetch).not.toHaveBeenCalled();
  client.clear();
});

it('refetches preferences after their measured freshness expires', async () => {
  vi.useFakeTimers();
  const client = createReaderQueryClient();
  seedPreferences(client, 'a', prefs);
  const fetch = vi.fn(() => Promise.resolve(prefs));
  await client.fetchQuery({ ...preferencesQueryOptions('a'), queryFn: fetch });
  expect(fetch).not.toHaveBeenCalled();
  vi.advanceTimersByTime(resourcePolicies.preferences.staleTime + 1);
  await client.fetchQuery({ ...preferencesQueryOptions('a'), queryFn: fetch });
  expect(fetch).toHaveBeenCalledTimes(1);
  vi.useRealTimers();
  client.clear();
});

it('rejects a preference read that answers for another owner', async () => {
  reply({ ...prefs, owner_id: 'foreign' });
  await expect(fetchConfirmedPreferences('a', new AbortController().signal))
    .rejects.toEqual(new ApiError(401));
});

it('never lets a delayed private response repopulate a cleared identity', async () => {
  const client = createReaderQueryClient();
  let resolve!: (value: unknown) => void;
  const pending = client.fetchQuery({ ...preferencesQueryOptions('a'),
    queryFn: () => new Promise<unknown>(done => { resolve = done; }) }).catch(() => undefined);
  client.clear();
  resolve(prefs);
  await pending;
  expect(client.getQueryData(queryKeys.preferences('a'))).toBeUndefined();
  client.clear();
});

it('reconciles a confirmed save into the preferences resource and cancels superseded reads', async () => {
  const client = createReaderQueryClient();
  let resolve!: (value: typeof prefs) => void;
  const pending = client.fetchQuery({ ...preferencesQueryOptions('a'),
    queryFn: () => new Promise<Preferences>(done => { resolve = done; }) }).catch(() => undefined);
  const saved: Preferences = { ...prefs, appearance: 'Light' };
  reply(saved);
  const observer = new MutationObserver(client, preferencesMutationOptions(client, 'a'));
  await observer.mutate({ patch: { appearance: 'Light' } });
  resolve(prefs);
  await pending;
  expect(client.getQueryData(queryKeys.preferences('a'))).toEqual(saved);
  client.clear();
});
