/** Ephemeral reader state; owner changes and late responses cannot share a transcript. */
import { useEffect, useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { ApiError, StreamlitAccess, currentSession, verifiedBootstrap, type Bookmarks, type Notebook, type NotebookList, type NotebookSettingsPatch, type Page, type Project, type Session, type Preferences } from './api';
import { moveThread, readMessagePage, readNotebookList, readThreadWorkspace, removeThread, updateNotebookSettings } from './api/client';
import { reconcileNotebooks, notebooksQueryOptions, seedNotebooks, withEntry, withoutEntry } from './api/workspaceNotebooks';
import { seedNotebookSettings, seedPreferences } from './api/workspaceSettings';
import { seedBookmarks } from './api/workspaceBookmarks';
import { seedProject } from './api/workspaceProject';
import { readProject } from './api/client';
import { queryKeys } from './api/queryKeys';

interface ReaderState {
  phase: 'checking' | 'signed-out' | 'ready' | 'error';
  session: Session | null; notebooks: NotebookList['notebooks'];
  page: Page | null; project: Project | null; busy: boolean; error: string;
  chatSummaries: NotebookList['chat_summaries'];
  preferences: Preferences | null;
  bookmarks: Bookmarks | null;
}
export const SIGN_OUT_SIGNAL = "codesign-signed-out";

const blank: ReaderState = { phase: 'checking', session: null, notebooks: [], chatSummaries: {}, page: null, project: null, preferences: null, bookmarks: null, busy: false, error: '' };

/** Own the session lifecycle and owner/revision-fenced list and page requests. */
export function useReader() {
  const queryClient = useQueryClient();
  const [state, setState] = useState<ReaderState>(blank);
  const generation = useRef(0);
  const controller = useRef(new AbortController());
  const current = useRef(state);
  current.current = state;

  function reset() {
    queryClient.clear();
    generation.current += 1;
    controller.current.abort();
    controller.current = new AbortController();
    current.current = blank;
    setState(blank);
  }

  function fail(error: unknown, epoch: number) {
    if (epoch !== generation.current || (error instanceof DOMException && error.name === 'AbortError')) return;
    if (error instanceof StreamlitAccess) {
      reset();
      window.location.replace('/streamlit/' + window.location.search);
    } else if (error instanceof ApiError && error.status === 401) {
      reset();
      setState({ ...blank, phase: 'signed-out' });
    } else if (error instanceof ApiError && error.status === 403) {
      reset();
      setState({ ...blank, phase: 'error', error: 'This account cannot access the student workspace.' });
    } else {
      setState(value => ({ ...value, busy: false, phase: value.session ? 'ready' : 'error',
        error: error instanceof ApiError && error.status === 409
          ? 'This notebook changed. Reopen it to read the latest saved history.'
          : 'Could not load saved work. Check your connection and try again.' }));
    }
  }

  async function reload() {
    reset();
    const epoch = generation.current;
    const signal = controller.current.signal;
    try {
      const { session, listing: list, preferences } = await verifiedBootstrap(signal);
      if (epoch !== generation.current) return;
      // The owner-verified bootstrap result seeds the preferences and listing
      // resources, so no component immediately refetches the same private values.
      seedPreferences(queryClient, session.owner_id, preferences);
      seedNotebooks(queryClient, session.owner_id, list);
      setState({ ...blank, phase: 'ready', session, preferences, notebooks: list.notebooks, chatSummaries: list.chat_summaries ?? {} });
    } catch (error) { fail(error, epoch); }
  }

  /** Deduplicate notebook reads in memory while revalidating ownership on every result. */
  function readNotebooks(owner: string, signal: AbortSignal): Promise<NotebookList> {
    return queryClient.fetchQuery({
      ...notebooksQueryOptions(owner),
      queryFn: async ({ signal: querySignal }) => {
        const requestSignal = AbortSignal.any([signal, querySignal]);
        const list = await readNotebookList(requestSignal);
        if (list.owner_id !== owner) throw new ApiError(401);
        return list;
      },
    });
  }

  async function open(notebookId: string, older = false, refresh = false, target?: string) {
    const snapshot = current.current;
    if (!snapshot.session || snapshot.busy) return;
    const epoch = ++generation.current;
    controller.current.abort();
    controller.current = new AbortController();
    const signal = controller.current.signal;
    setState(value => ({ ...value, page: older || refresh ? value.page : null, project: older || refresh ? value.project : null, busy: true, error: '' }));
    try {
      const cursor = older ? snapshot.page?.next_cursor : null;
      // Initial opens and refreshes use one bounded workspace read; loading
      // earlier pages keeps the revision-bound pagination lifecycle.
      const [opened, list] = await Promise.all([
        older
          ? Promise.all([readMessagePage(notebookId, signal, cursor), readProject(notebookId, signal)])
            .then(([first, readProjectView]) => ({ page: first, project: readProjectView, workspace: null }))
          : readThreadWorkspace(notebookId, signal)
            .then(read => ({ page: read.page, project: read.project, workspace: read })),
        refresh ? readNotebooks(snapshot.session.owner_id, signal).catch(error => {
          if (error instanceof ApiError && [401, 403].includes(error.status)) throw error;
          return null;
        }) : Promise.resolve(null),
      ]);
      let page = opened.page;
      const { project, workspace } = opened;
      // Follow revision-bound pages so an old bookmark opens its original with surrounding context.
      while (target && !page.messages.some(message => message.id === target) && page.next_cursor) {
        const earlier = await readMessagePage(notebookId, signal, page.next_cursor, 100);
        if (earlier.owner_id !== page.owner_id || earlier.notebook.id !== notebookId || earlier.conversation_revision !== page.conversation_revision) throw new ApiError(409);
        page = { ...page, messages: [...earlier.messages, ...page.messages], next_cursor: earlier.next_cursor };
      }
      if (target && !page.messages.some(message => message.id === target)) throw new ApiError(404);
      const verified = await currentSession(signal);
      if (epoch !== generation.current) return;
      if (page.owner_id !== snapshot.session.owner_id || project.owner_id !== page.owner_id || project.thread_id !== notebookId || verified.owner_id !== page.owner_id || (list && list.owner_id !== page.owner_id)
        || (workspace && (workspace.owner_id !== page.owner_id
          || workspace.bookmarks.thread_id !== notebookId || workspace.settings.notebook.id !== notebookId))) { void reload(); return; }
      if (older && snapshot.page && page.conversation_revision !== snapshot.page.conversation_revision) throw new ApiError(409);
      if (workspace) {
        seedNotebookSettings(queryClient, snapshot.session.owner_id, notebookId, workspace.settings);
        seedBookmarks(queryClient, snapshot.session.owner_id, notebookId, workspace.bookmarks);
        seedProject(queryClient, snapshot.session.owner_id, notebookId, project);
      }
      const previous = snapshot.page;
      const keepWindow = refresh && previous && page.conversation_revision === previous.conversation_revision
        && page.messages.some(message => previous.messages.some(prior => prior.id === message.id));
      const messages = older && previous ? [...page.messages, ...previous.messages]
        : keepWindow ? [...previous.messages.filter(prior => !page.messages.some(message => message.id === prior.id)), ...page.messages] : page.messages;
      setState(value => ({ ...value, busy: false, project,
        bookmarks: workspace ? workspace.bookmarks : value.bookmarks,
        notebooks: (list?.notebooks ?? value.notebooks).map(item => item.id === page.notebook.id ? page.notebook : item),
        chatSummaries: list?.chat_summaries ?? value.chatSummaries,
        page: { ...page, messages,
        next_cursor: keepWindow ? previous.next_cursor : page.next_cursor } }));
      return true;
    } catch (error) { fail(error, epoch); }
  }

  async function refreshList() {
    const snapshot = current.current;
    const epoch = generation.current;
    if (!snapshot.session) throw new Error('Session unavailable');
    const signal = controller.current.signal;
    // A write reconciliation must not reuse a read that started before the write.
    await queryClient.cancelQueries({ queryKey: queryKeys.notebooks(snapshot.session.owner_id) });
    if (epoch !== generation.current) throw new Error('View changed');
    const list = await readNotebooks(snapshot.session.owner_id, signal);
    const verified = await currentSession(signal);
    if (epoch !== generation.current) throw new Error('View changed');
    if (list.owner_id !== snapshot.session.owner_id || verified.owner_id !== list.owner_id) { void reload(); throw new Error('Owner changed'); }
    setState(value => {
      const pageId = value.page?.notebook.id;
      const notebook = pageId ? list.notebooks.find(item => item.id === pageId) : null;
      return { ...value, notebooks: list.notebooks, chatSummaries: list.chat_summaries ?? {},
        page: notebook && value.page ? { ...value.page, notebook } : null,
        project: notebook ? value.project : null };
    });
    return list;
  }

  /** Write through a generated contract, reconcile the confirmed result, then revalidate the list. */
  async function updateChat(id: string, action: 'move' | 'settings' | 'remove', body: object,
    saved: (entry: Notebook | undefined) => boolean) {
    const epoch = generation.current;
    const owner = current.current.session?.owner_id;
    if (!owner) throw new Error('Session unavailable');
    let confirmed: Notebook | 'removed' | null = null;
    try {
      if (action === 'move') {
        confirmed = (await moveThread(id, (body as { parent_notebook_id: string | null }).parent_notebook_id,
          controller.current.signal)).notebook;
      } else if (action === 'settings') {
        confirmed = (await updateNotebookSettings(id, body as NotebookSettingsPatch,
          controller.current.signal)).notebook;
      } else {
        await removeThread(id, controller.current.signal);
        confirmed = 'removed';
      }
    } catch { /* A lost response can still leave a saved change. Reconcile below. */ }
    if (epoch !== generation.current) throw new Error('View changed');
    const result = confirmed;
    if (result !== null) {
      await reconcileNotebooks(queryClient, owner, list => result === 'removed'
        ? withoutEntry(list, id) : withEntry(list, result));
    }
    const list = await refreshList();
    if (!saved(list.notebooks.find(entry => entry.id === id))) throw new Error('Change not saved');
  }

  function moveChat(id: string, destination: string | null) {
    return updateChat(id, 'move', { parent_notebook_id: destination }, entry => !!entry && (entry.parent_notebook_id ?? null) === destination);
  }

  function renameChat(id: string, name: string) {
    return updateChat(id, 'settings', { name }, entry => entry?.name === name);
  }

  function pinChat(id: string, pinned: boolean) {
    return updateChat(id, 'settings', { pinned }, entry => entry?.pinned === pinned);
  }

  async function deleteChat(id: string) {
    const owner = current.current.session?.owner_id;
    await updateChat(id, 'remove', { confirmed: true }, entry => !entry);
    try {
      sessionStorage.removeItem(`codesign-mode:${owner}:${id}`);
      sessionStorage.removeItem(`codesign-lecture:${owner}:${id}`);
      const selected = `codesign-selected:${owner}`;
      if (sessionStorage.getItem(selected) === id) sessionStorage.removeItem(selected);
    } catch { /* Browser tab storage is optional. */ }
  }

  async function shareChat(chat: Notebook) {
    const signal = controller.current.signal;
    const snapshot = current.current.session;
    const response = await fetch(`/api/v1/reader/threads/${encodeURIComponent(chat.id)}/transcript.txt`, {
      credentials: 'same-origin', cache: 'no-store', signal,
    });
    if (!response.ok) throw new ApiError(response.status);
    const blob = await response.blob();
    const owner = await currentSession(signal);
    if (signal.aborted || owner.owner_id !== snapshot?.owner_id) throw new Error('Owner changed');
    const file = new File([blob], `${chat.name.replace(/[\\/]/g, '_')}-transcript.txt`, { type: 'text/plain' });
    if (navigator.canShare?.({ files: [file] })) {
      try {
        await navigator.share({ files: [file] });
        return 'Transcript shared.';
      } catch (error) {
        if (error instanceof DOMException && error.name === 'AbortError') return '';
        if (!(error instanceof DOMException && error.name === 'NotAllowedError')) throw error;
      }
    }
    const url = URL.createObjectURL(file);
    const link = document.createElement('a');
    link.href = url;
    link.download = file.name;
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    return 'Transcript downloaded.';
  }

  async function startGuest() {
    reset();
    const epoch = generation.current;
    try {
      const response = await fetch('/api/v1/auth/guest/start', { method: 'POST', credentials: 'same-origin',
        cache: 'no-store', signal: controller.current.signal });
      if (!response.ok) throw new ApiError(response.status);
      if (epoch === generation.current) void reload();
    } catch (error) {
      if (epoch !== generation.current) return;
      setState({ ...blank, phase: 'signed-out', error: error instanceof ApiError && error.status === 429
        ? 'Guest entry is busy. Wait a minute and try again, or ask your lecturer for help.'
        : 'Guest entry is unavailable. Try again or sign in.' });
    }
  }

  useEffect(() => {
    void reload();
    let lastCheck = Date.now();
    let checking = false;
    const visibility = () => { if (!document.hidden) void check(); };
    const pageHide = () => reset();
    const pageShow = (event: PageTransitionEvent) => { if (event.persisted) void reload(); };
    const check = async () => {
      const epoch = generation.current;
      const owner = current.current.session?.owner_id;
      if (!owner || document.hidden || checking || Date.now() - lastCheck < 60_000) return;
      checking = true;
      lastCheck = Date.now();
      try {
        const session = await currentSession(controller.current.signal);
        if (epoch === generation.current && owner !== session.owner_id) void reload();
      } catch (error) { fail(error, epoch); }
      finally { checking = false; }
    };
    document.addEventListener('visibilitychange', visibility);
    window.addEventListener('focus', check);
    window.addEventListener('pagehide', pageHide);
    window.addEventListener('pageshow', pageShow);
    const onStorage = (event: StorageEvent) => {
      if (event.key !== SIGN_OUT_SIGNAL || !event.newValue) return;
      reset();
      setState({ ...blank, phase: 'signed-out' });
    };
    window.addEventListener('storage', onStorage);
    const interval = window.setInterval(check, 60_000);
    return () => {
      queryClient.clear();
      controller.current.abort();
      generation.current += 1;
      document.removeEventListener('visibilitychange', visibility);
      window.removeEventListener('focus', check);
      window.removeEventListener('pagehide', pageHide);
      window.removeEventListener('pageshow', pageShow);
      window.removeEventListener('storage', onStorage);
      window.clearInterval(interval);
    };
  }, []);

  return { ...state, reload, open, startGuest, refreshList, moveChat, renameChat, pinChat, deleteChat, shareChat };
}
