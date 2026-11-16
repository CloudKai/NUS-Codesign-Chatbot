/** Ephemeral reader state; owner changes and late responses cannot share a transcript. */
import { useEffect, useRef, useState } from 'react';
import { ApiError, currentSession, get, type NotebookList, type Page, type Session } from './api';

interface ReaderState {
  phase: 'checking' | 'signed-out' | 'ready' | 'error';
  session: Session | null; notebooks: NotebookList['notebooks'];
  page: Page | null; busy: boolean; error: string;
}
const blank: ReaderState = { phase: 'checking', session: null, notebooks: [], page: null, busy: false, error: '' };

/** Own the session lifecycle and owner/revision-fenced list and page requests. */
export function useReader() {
  const [state, setState] = useState<ReaderState>(blank);
  const generation = useRef(0);
  const controller = useRef(new AbortController());
  const current = useRef(state);
  current.current = state;

  function reset() {
    generation.current += 1;
    controller.current.abort();
    controller.current = new AbortController();
    current.current = blank;
    setState(blank);
  }

  function fail(error: unknown, epoch: number) {
    if (epoch !== generation.current || (error instanceof DOMException && error.name === 'AbortError')) return;
    if (error instanceof ApiError && error.status === 401) {
      reset();
      setState({ ...blank, phase: 'signed-out' });
    } else if (error instanceof ApiError && error.status === 403) {
      reset();
      setState({ ...blank, phase: 'error', error: 'This reader is for student notebooks. Open Streamlit to continue.' });
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
      const session = await currentSession(signal);
      const list = await get<NotebookList>('/api/v1/reader/threads', signal);
      const verified = await currentSession(signal);
      if (epoch !== generation.current) return;
      if (session.owner_id !== list.owner_id || verified.owner_id !== session.owner_id) { void reload(); return; }
      setState({ ...blank, phase: 'ready', session: verified, notebooks: list.notebooks });
    } catch (error) { fail(error, epoch); }
  }

  async function open(notebookId: string, older = false) {
    const snapshot = current.current;
    if (!snapshot.session || snapshot.busy) return;
    const epoch = ++generation.current;
    controller.current.abort();
    controller.current = new AbortController();
    const signal = controller.current.signal;
    setState(value => ({ ...value, page: older ? value.page : null, busy: true, error: '' }));
    try {
      const cursor = older ? snapshot.page?.next_cursor : null;
      const query = new URLSearchParams({ limit: '20' });
      if (cursor) query.set('cursor', cursor);
      const page = await get<Page>(`/api/v1/reader/threads/${encodeURIComponent(notebookId)}/messages/page?${query}`, signal);
      const verified = await currentSession(signal);
      if (epoch !== generation.current) return;
      if (page.owner_id !== snapshot.session.owner_id || verified.owner_id !== page.owner_id) { void reload(); return; }
      if (older && snapshot.page && page.conversation_revision !== snapshot.page.conversation_revision) throw new ApiError(409);
      setState(value => ({ ...value, busy: false, page: { ...page,
        messages: older && snapshot.page ? [...page.messages, ...snapshot.page.messages] : page.messages } }));
    } catch (error) { fail(error, epoch); }
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
        : 'Guest entry is unavailable. Try again or sign in through Streamlit.' });
    }
  }

  useEffect(() => {
    void reload();
    const hide = () => { if (document.hidden) reset(); else void reload(); };
    const pageHide = () => reset();
    const pageShow = (event: PageTransitionEvent) => { if (event.persisted) void reload(); };
    const check = async () => {
      const epoch = generation.current;
      const owner = current.current.session?.owner_id;
      if (!owner || document.hidden) return;
      try {
        const session = await currentSession(controller.current.signal);
        if (epoch === generation.current && owner !== session.owner_id) void reload();
      } catch (error) { fail(error, epoch); }
    };
    document.addEventListener('visibilitychange', hide);
    window.addEventListener('focus', check);
    window.addEventListener('pagehide', pageHide);
    window.addEventListener('pageshow', pageShow);
    const interval = window.setInterval(check, 15000);
    return () => {
      controller.current.abort();
      generation.current += 1;
      document.removeEventListener('visibilitychange', hide);
      window.removeEventListener('focus', check);
      window.removeEventListener('pagehide', pageHide);
      window.removeEventListener('pageshow', pageShow);
      window.clearInterval(interval);
    };
  }, []);

  return { ...state, reload, open, startGuest };
}
