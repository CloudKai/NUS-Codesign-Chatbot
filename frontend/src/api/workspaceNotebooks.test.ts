/** Owner-fenced notebook-list resource: confirmed-write reconciliation and identity races. */
import { afterEach, expect, it, vi } from 'vitest';
import { createReaderQueryClient } from './queryClient';
import { queryKeys } from './queryKeys';
import { fetchConfirmedNotebooks, notebooksPolicies, notebooksQueryOptions, reconcileNotebooks, seedNotebooks, withEntry, withoutEntry } from './workspaceNotebooks';
import { browserClient } from './client';
import { ApiError } from './errors';
import type { NotebookList } from '../api';

const list: NotebookList = { owner_id: 'a', notebooks: [
  { id: 'nb', name: 'Studio', kind: 'notebook', pinned: false, parent_notebook_id: null },
  { id: 'chat', name: 'New Chat', kind: 'chat', pinned: false, parent_notebook_id: 'nb' },
], chat_summaries: { chat: { preview: 'Hello there', activity_at: '2026-11-24T00:00:00Z' } } };

afterEach(() => vi.unstubAllGlobals());

it('keeps reads immediately stale while retaining the last confirmed list for reconciliation', () => {
  expect(notebooksPolicies.staleTime).toBe(0);
  expect(notebooksPolicies.gcTime).toBeGreaterThan(0);
});

it('rejects a listing that answers for another owner', async () => {
  browserClient.setConfig({ baseUrl: 'https://app.test' });
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(Response.json({ ...list, owner_id: 'foreign' }))));
  await expect(fetchConfirmedNotebooks('a', new AbortController().signal))
    .rejects.toEqual(new ApiError(401));
});

it('reconciles a confirmed entry without dropping other sidebar identities', () => {
  const created = { id: 'new', name: 'Campus wellbeing', kind: 'notebook' as const, pinned: false, parent_notebook_id: null };
  expect(withEntry(list, created).notebooks.map(item => item.id)).toEqual(['new', 'nb', 'chat']);
  const renamed = withEntry(list, { ...list.notebooks[1], name: 'Renamed chat' });
  expect(renamed.notebooks).toHaveLength(2);
  expect(renamed.notebooks.find(item => item.id === 'chat')?.name).toBe('Renamed chat');
  expect(renamed.notebooks.find(item => item.id === 'nb')).toEqual(list.notebooks[0]);
});

it('drops one confirmed deletion and its bounded preview only', () => {
  const removedNotebook = withoutEntry(list, 'nb');
  expect(removedNotebook.notebooks.map(item => item.id)).toEqual(['chat']);
  expect(removedNotebook.chat_summaries).toEqual(list.chat_summaries);
  const removedChat = withoutEntry(list, 'chat');
  expect(removedChat.notebooks).toEqual([list.notebooks[0]]);
  expect(removedChat.chat_summaries).toEqual({});
});

it('reconciles a confirmed write and cancels superseded list reads', async () => {
  const client = createReaderQueryClient();
  seedNotebooks(client, 'a', list);
  let resolve!: (value: NotebookList) => void;
  const pending = client.fetchQuery({ ...notebooksQueryOptions('a'),
    queryFn: () => new Promise<NotebookList>(done => { resolve = done; }) }).catch(() => undefined);
  const moved = { ...list.notebooks[1], parent_notebook_id: null };
  await reconcileNotebooks(client, 'a', value => withEntry(value, moved));
  resolve(list); // A pre-write read finishing late must not roll back the confirmed write.
  await pending;
  expect(client.getQueryData(queryKeys.notebooks('a'))).toEqual(withEntry(list, moved));
  client.clear();
});

it('never writes a confirmed result into another owner resource', async () => {
  const client = createReaderQueryClient();
  seedNotebooks(client, 'b', list);
  await reconcileNotebooks(client, 'a', value => withoutEntry(value, 'nb'));
  expect(client.getQueryData(queryKeys.notebooks('b'))).toEqual(list);
  expect(client.getQueryData(queryKeys.notebooks('a'))).toBeUndefined();
  client.clear();
});
