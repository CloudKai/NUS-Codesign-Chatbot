/**
 * @vitest-environment jsdom
 */
/** Observed save feedback and reload persistence through the real settings surface. */
import { createRef } from 'react';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClientProvider } from '@tanstack/react-query';
import { WorkspaceTools, type WorkspaceActions } from './WorkspaceTools';
import { createReaderQueryClient } from './api/queryClient';
import { seedPreferences } from './api/workspaceSettings';
import { seedNotebooks } from './api/workspaceNotebooks';
import { queryKeys } from './api/queryKeys';
import { browserClient } from './api/client';
import type { NotebookList, NotebookSettings, Preferences, Session } from './api';

const session: Session = { owner_id: 'a', kind: 'guest', display_name: 'Student' };
const prefs: Preferences = { owner_id: 'a', appearance: 'Dark', display_name: 'Kai',
  reduce_motion: false, default_mode: 'project', starter_prompts: true };
const list: NotebookList = { owner_id: 'a', notebooks: [
  { id: 'nb', name: 'Studio', kind: 'notebook', pinned: false, parent_notebook_id: null },
  { id: 'chat', name: 'New Chat', kind: 'chat', pinned: false, parent_notebook_id: 'nb' },
], chat_summaries: { chat: { preview: 'Hello there', activity_at: '2026-11-24T00:00:00Z' } } };
const nbSettings: NotebookSettings = { owner_id: 'a', notebook: list.notebooks[0],
  response_detail: 'short', response_language: 'English', selected_model: 'mock',
  reasoning_effort: null, assignment: {}, models: [], chat_model_label: 'Mock coach' };

beforeAll(() => {
  window.matchMedia = (query: string) => ({
    matches: false, media: query, onchange: null, addListener() {}, removeListener() {},
    addEventListener() {}, removeEventListener() {}, dispatchEvent: () => false,
  });
  // jsdom renders native dialogs but does not implement opening them.
  HTMLDialogElement.prototype.showModal ??= function showModal(this: HTMLDialogElement) { this.open = true; };
  HTMLDialogElement.prototype.close ??= function close(this: HTMLDialogElement) { this.open = false; };
});

afterEach(() => { cleanup(); vi.unstubAllGlobals(); document.body.innerHTML = ''; });

function saved(appearance: Preferences['appearance']): Preferences {
  return { ...prefs, appearance };
}

/** Mount the real workspace tools with one seeded Query client and stubbed transport. */
function renderTools(client = createReaderQueryClient(), seed = true, thread?: string) {
  if (seed) seedPreferences(client, 'a', prefs);
  const themeHost = document.createElement('div');
  const settingsHost = document.createElement('div');
  document.body.append(themeHost, settingsHost);
  browserClient.setConfig({ baseUrl: 'https://app.test' });
  const fetch = vi.fn();
  vi.stubGlobal('fetch', fetch);
  const changed = vi.fn().mockResolvedValue(undefined);
  const actions = createRef<WorkspaceActions>();
  const tools = render(
    <QueryClientProvider client={client}>
      <WorkspaceTools session={session} thread={thread} disabled={false} changed={changed} expired={vi.fn()}
        blocked={vi.fn()} themeHost={themeHost} settingsHost={settingsHost}
        ref={actions} openSettings={vi.fn()} closeSettings={vi.fn()}
        onPreferences={vi.fn()} initialPreferences={prefs}/>
    </QueryClientProvider>);
  return { client, fetch, changed, actions, ...tools };
}

describe('workspace settings surface', () => {
  it('saves a theme choice, confirms it, and applies it without extra preference reads', async () => {
    const { fetch, client } = renderTools();
    fetch.mockImplementation(() => Promise.resolve(Response.json(saved('Light'))));
    fireEvent.click(screen.getByRole('button', { name: 'Switch to day mode' }));
    await waitFor(async () => expect((await screen.findAllByText('Changes saved.')).length).toBeGreaterThan(0));
    expect(fetch).toHaveBeenCalledTimes(3);
    const request = fetch.mock.calls[1][0] as Request;
    expect(request.method).toBe('POST');
    expect(new URL(request.url).pathname).toBe('/api/v1/reader/preferences');
    expect(await request.text()).toBe(JSON.stringify({ appearance: 'Light' }));
    // The confirmed write response reconciles the resource; no read replays it.
    expect(fetch.mock.calls.filter(([request]) => (request as Request).method === 'GET'
      && new URL((request as Request).url).pathname === '/api/v1/reader/preferences')).toHaveLength(0);
    expect(document.documentElement.dataset.appearance).toBe('Light');
    expect(client.getQueryData(['reader', 'a', 'preferences'])).toEqual(saved('Light'));
  });

  it('reuses the confirmed save on remount without a duplicate preference read', async () => {
    const first = renderTools();
    first.fetch.mockImplementation(() => Promise.resolve(Response.json(saved('Light'))));
    fireEvent.click(screen.getByRole('button', { name: 'Switch to day mode' }));
    await waitFor(async () => expect((await screen.findAllByText('Changes saved.')).length).toBeGreaterThan(0));
    const { client } = first;
    first.unmount();

    const second = renderTools(client, false);
    expect(screen.getByRole('button', { name: 'Switch to night mode' })).toBeTruthy();
    expect(second.fetch).not.toHaveBeenCalled();
  });

  it('never persists private Query state into shared browser storage', async () => {
    const { fetch } = renderTools();
    fetch.mockImplementation(() => Promise.resolve(Response.json(saved('Light'))));
    fireEvent.click(screen.getByRole('button', { name: 'Switch to day mode' }));
    await waitFor(async () => expect((await screen.findAllByText('Changes saved.')).length).toBeGreaterThan(0));
    expect(sessionStorage.length).toBe(0);
    expect(localStorage.length).toBe(0);
  });

  it('rejects a saved answer for another owner and never applies or caches it', async () => {
    const { fetch, client, expiredAccess } = renderToolsWithExpired();
    fetch.mockResolvedValue(Response.json({ ...saved('Light'), owner_id: 'foreign' }));
    fireEvent.click(screen.getByRole('button', { name: 'Switch to day mode' }));
    await waitFor(() => expect(expiredAccess).toHaveBeenCalled());
    expect(client.getQueryData(['reader', 'a', 'preferences'])).toEqual(prefs);
    expect(document.documentElement.dataset.appearance).toBe('Dark');
  });
});

function renderToolsWithExpired() {
  const client = createReaderQueryClient();
  seedPreferences(client, 'a', prefs);
  const themeHost = document.createElement('div');
  const settingsHost = document.createElement('div');
  document.body.append(themeHost, settingsHost);
  browserClient.setConfig({ baseUrl: 'https://app.test' });
  const fetch = vi.fn();
  vi.stubGlobal('fetch', fetch);
  const expiredAccess = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <WorkspaceTools session={session} disabled={false} changed={vi.fn().mockResolvedValue(undefined)}
        expired={expiredAccess} blocked={vi.fn()} themeHost={themeHost} settingsHost={settingsHost}
        ref={createRef<WorkspaceActions>()} openSettings={vi.fn()} closeSettings={vi.fn()}
        onPreferences={vi.fn()} initialPreferences={prefs}/>
    </QueryClientProvider>);
  return { client, fetch, expiredAccess };
}

describe('notebook lifecycle through the generated contracts', () => {
  it('creates a notebook through the generated POST contract and reconciles the sidebar resource', async () => {
    const client = createReaderQueryClient();
    seedNotebooks(client, 'a', list);
    const { fetch, actions } = renderTools(client, true);
    const created = { id: 'new', name: 'Campus wellbeing', kind: 'notebook', pinned: false, parent_notebook_id: null };
    fetch.mockImplementation((request: Request) => {
      if (request.method === 'POST') {
        return Promise.resolve(Response.json({ ...nbSettings, notebook: created }));
      }
      return Promise.resolve(Response.json(session));
    });
    act(() => actions.current?.promptNotebook());
    fireEvent.change(screen.getByLabelText('Notebook name'), { target: { value: 'Campus wellbeing' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create notebook' }));
    await waitFor(async () => expect((await screen.findAllByText('Changes saved.')).length).toBeGreaterThan(0));
    const request = (fetch.mock.calls.find(([sent]) => (sent as Request).method === 'POST'))![0] as Request;
    expect(new URL(request.url).pathname).toBe('/api/v1/reader/threads');
    expect(await request.text()).toBe(JSON.stringify({ name: 'Campus wellbeing' }));
    const cached = client.getQueryData(queryKeys.notebooks('a')) as NotebookList;
    expect(cached.notebooks[0]).toEqual(created);
    expect(cached.notebooks.map(item => item.id)).toEqual(['new', 'nb', 'chat']);
  });

  it('settings omit the model name and current-chat rename, assignment and delete controls', async () => {
    const client = createReaderQueryClient();
    seedNotebooks(client, 'a', list);
    renderTools(client, true, 'nb');
    expect(await screen.findByText('Preferences are saved to your workspace.')).toBeTruthy();
    expect(screen.queryByText('Current notebook')).toBeNull();
    expect(screen.queryByText('Current chat')).toBeNull();
    expect(screen.queryByText('Model')).toBeNull();
    expect(screen.queryByRole('button', { name: /Delete notebook/ })).toBeNull();
    expect(screen.queryByLabelText('Assignment title')).toBeNull();
  });
});
