/**
 * @vitest-environment jsdom
 */
/** Measured startup/open/switch/revisit request counts for the aggregated workspace read. */
import { afterEach, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import { useReader } from './useReader';
import { createReaderQueryClient } from './api/queryClient';
import { browserClient } from './api/client';
import type { NotebookList, NotebookSettings, Page, Preferences, Project, Session } from './api';

const session: Session = { owner_id: 'a', kind: 'registered', display_name: 'Student' };
const preferences: Preferences = { owner_id: 'a', appearance: 'System', display_name: 'Kai',
  reduce_motion: false, default_mode: 'improve', starter_prompts: true };
const listing: NotebookList = { owner_id: 'a', notebooks: [
  { id: 't1', name: 'First', kind: 'notebook', pinned: false, parent_notebook_id: null },
  { id: 't2', name: 'Second', kind: 'notebook', pinned: false, parent_notebook_id: null },
], chat_summaries: {} };

function entry(id: string) {
  return { id, name: 'Chat', kind: 'notebook' as const, pinned: false, parent_notebook_id: null };
}

function workspace(id: string) {
  const page: Page = { owner_id: 'a', notebook: entry(id), messages: [], next_cursor: null,
    total_count: 0, conversation_revision: 1 };
  const project: Project = { owner_id: 'a', thread_id: id, current_stage: 'framing', stages: [],
    pending: null, review: { summary: '', strengths: [], improvements: [], facione_scores: [],
      project_brief: { status: 'missing', version: '', brief: null } } };
  const settings: NotebookSettings = { owner_id: 'a', notebook: entry(id),
    response_detail: 'short', response_language: 'English', selected_model: 'mock',
    reasoning_effort: null, assignment: {}, models: [], chat_model_label: 'Mock coach' };
  return { owner_id: 'a', page, project,
    bookmarks: { owner_id: 'a', thread_id: id, conversation_revision: 1, messages: [] }, settings };
}

afterEach(() => vi.unstubAllGlobals());

it('opens, switches and revisits chats with one workspace read plus the identity probe', async () => {
  browserClient.setConfig({ baseUrl: 'https://app.test' });
  const fetch = vi.fn((request: Request) => {
    const path = new URL(request.url).pathname;
    if (path === '/api/v1/reader/bootstrap') {
      return Promise.resolve(Response.json({ session, listing, preferences }));
    }
    if (path === '/api/v1/reader/session') return Promise.resolve(Response.json(session));
    if (path.endsWith('/workspace')) return Promise.resolve(Response.json(workspace(path.split('/')[5])));
    return Promise.resolve(Response.json({ detail: 'unexpected request' }, { status: 500 }));
  });
  vi.stubGlobal('fetch', fetch);
  const client = createReaderQueryClient();
  const hook = renderHook(() => useReader(), { wrapper: ({ children }) =>
    <QueryClientProvider client={client}>{children}</QueryClientProvider> });
  const { result, unmount } = hook;
  try {
    await waitFor(() => expect(result.current.phase).toBe('ready'));
    const afterBootstrap = fetch.mock.calls.length;

    await act(() => result.current.open('t1'));
    await waitFor(() => expect(result.current.page?.notebook.id).toBe('t1'));
    const afterFirstOpen = fetch.mock.calls.length;

    await act(() => result.current.open('t2'));
    await waitFor(() => expect(result.current.page?.notebook.id).toBe('t2'));
    const afterSwitch = fetch.mock.calls.length;

    await act(() => result.current.open('t1'));
    await waitFor(() => expect(result.current.page?.notebook.id).toBe('t1'));
    const afterRevisit = fetch.mock.calls.length;

    // Aggregated baseline: one workspace read plus the identity probe per open.
    expect(afterFirstOpen - afterBootstrap).toBe(2);
    expect(afterSwitch - afterFirstOpen).toBe(2);
    expect(afterRevisit - afterSwitch).toBe(2);
    // The open reads must not trigger duplicate component fetches.
    const paths = fetch.mock.calls.map(([request]) => new URL((request as Request).url).pathname);
    expect(paths.filter(path => path.endsWith('/bookmarks'))).toHaveLength(0);
    expect(paths.filter(path => path.endsWith('/settings'))).toHaveLength(0);
    // The verified workspace response seeded the settings resource.
    expect(client.getQueryData(['reader', 'a', 'notebook', 't1', 'settings'])).toEqual(workspace('t1').settings);
  } finally { unmount(); }
});
