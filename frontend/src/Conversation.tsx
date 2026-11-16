/** Lecture composer, exact-request reconciliation and saved citation inspection. */
import { useEffect, useRef, useState } from 'react';
import { ApiError, currentSession, get, type Page, type Project } from './api';
import { Sources } from './Sources';
import { ThinkingPath } from './ThinkingPath';
import { isTurn, readStream, type Citation, type Event } from './stream';

type Intent = 'lecture' | 'project';
interface Receipt { key: string; text: string; intent?: Intent }
interface Draft { text: string; pending: Receipt | null; intent?: Intent }
const empty: Draft = { text: '', pending: null };

/** Read only this owner's tab-scoped unsent text and recovery identity; never store replies. */
function restore(key: string): Draft {
  try {
    const value = JSON.parse(sessionStorage.getItem(key) || 'null');
    if (!value || typeof value.text !== 'string') return empty;
    const pending = value.pending;
    return { text: value.text, intent: value.intent === 'project' ? 'project' : 'lecture', pending: pending && typeof pending.key === 'string' && typeof pending.text === 'string' ? pending : null };
  } catch { return empty; }
}

/** Keep draft, focus and loaded transcript stable during progress and evidence inspection. */
export function Conversation({ page, project, owner, refresh, expired, busy, loadEarlier }: {
  page: Page; project: Project; owner: string; refresh: () => Promise<void>; expired: () => void;
  busy: boolean; loadEarlier: () => Promise<void>;
}) {
  const storageKey = `codesign-lecture:${owner}:${page.notebook.id}`;
  const initial = useRef(restore(storageKey));
  const [intent, setIntent] = useState<Intent>(initial.current.intent || 'lecture');
  const [pathOpen, setPathOpen] = useState(false);
  const pathToggle = useRef<HTMLButtonElement>(null);
  const [sourceUncertain, setSourceUncertain] = useState(false);
  const [moving, setMoving] = useState(false);
  const [projectUncertain, setProjectUncertain] = useState(false);
  const intentRef = useRef(intent);
  intentRef.current = intent;
  const [text, setText] = useState(initial.current.text);
  const [pending, setPending] = useState<Receipt | null>(initial.current.pending);
  const pendingRef = useRef(pending);
  const textRef = useRef(text);
  const [watching, setWatching] = useState(false);
  const [checking, setChecking] = useState(false);
  const [checkedKey, setCheckedKey] = useState('');
  const [status, setStatus] = useState('');
  const [preview, setPreview] = useState('');
  const [storageError, setStorageError] = useState(false);
  const [evidence, setEvidence] = useState<{ citation: Citation; message: string } | null>(null);
  const [downloadError, setDownloadError] = useState('');
  const active = useRef(true);
  const lock = useRef(false);
  const controller = useRef(new AbortController());
  const composer = useRef<HTMLTextAreaElement>(null);
  const evidenceHeading = useRef<HTMLHeadingElement>(null);
  const citationButton = useRef<HTMLButtonElement | null>(null);
  const returnScroll = useRef(0);
  const path = `/api/v1/reader/threads/${encodeURIComponent(page.notebook.id)}`;
  textRef.current = text;
  pendingRef.current = pending;

  function remember(nextText: string, nextPending: Receipt | null) {
    textRef.current = nextText;
    pendingRef.current = nextPending;
    setText(nextText);
    setPending(nextPending);
    try { sessionStorage.setItem(storageKey, JSON.stringify({ text: nextText, pending: nextPending, intent: intentRef.current })); }
    catch { setStorageError(true); }
  }

  async function verify() {
    const session = await currentSession(controller.current.signal);
    if (!active.current) throw new Error('View closed');
    if (session.owner_id !== owner) { expired(); throw new Error('Session changed'); }
  }

  async function reconcile(receipt: Receipt) {
    setChecking(true);
    setCheckedKey('');
    setPreview('');
    try {
      await verify();
      const saved = await get<unknown>(`${path}/coach-turn?${new URLSearchParams({ idempotency_key: receipt.key })}`, controller.current.signal);
      await verify();
      if (saved !== null && !isTurn(saved)) throw new Error('Malformed saved reply');
      if (saved) {
        remember(textRef.current === receipt.text ? '' : textRef.current, null);
        setStatus('Answer saved.');
        await refresh();
      } else {
        setCheckedKey(receipt.key);
        setStatus('No saved answer found yet. It may still be running. Check again, or retry this same question with its original request identity.');
      }
    } catch (error) {
      if (!active.current) return;
      if (error instanceof ApiError && [401, 403].includes(error.status)) expired();
      else setStatus('Could not check the saved answer. Keep this question and check again when connected.');
    } finally { if (active.current) setChecking(false); }
  }

  async function send(retry = false) {
    if (lock.current || busy || moving || sourceUncertain || projectUncertain || (!retry && (pendingRef.current || !textRef.current.trim()))) return;
    if (retry && checkedKey !== pendingRef.current?.key) return;
    lock.current = true;
    const receipt = retry ? pendingRef.current! : { key: crypto.randomUUID(), text: textRef.current, intent: intentRef.current };
    if (!receipt) { lock.current = false; return; }
    remember(textRef.current, receipt);
    setWatching(true);
    setPreview('');
    setStatus('Connecting…');
    controller.current.abort();
    controller.current = new AbortController();
    let terminalError: Event & { event: 'error' } | null = null;
    try {
      await verify();
      const response = await fetch(`${path}/${receipt.intent || 'lecture'}/stream`, {
        method: 'POST', credentials: 'same-origin', cache: 'no-store', signal: controller.current.signal,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ student_message: receipt.text, idempotency_key: receipt.key }),
      });
      if (!response.ok) throw new ApiError(response.status);
      await readStream(response, page.notebook.id, receipt.key, event => {
        if (!active.current) return;
        if (event.event === 'started') setStatus('Question accepted.');
        if (event.event === 'status') setStatus(({ queued: 'Waiting for capacity…', retrieving: 'Finding evidence…', thinking: 'Preparing an answer…', saving: 'Saving answer…' })[event.phase]);
        if (event.event === 'reply_ready') { setPreview(event.text); setStatus('Preview — waiting for saved completion.'); }
        if (event.event === 'error') { terminalError = event; setPreview(''); }
      });
    } catch (error) {
      if (active.current && error instanceof ApiError && [401, 403].includes(error.status)) { expired(); return; }
    } finally {
      if (active.current) {
        setPreview('');
        setWatching(false);
        // Cancellation, malformed records and EOF are ambiguous: only GET reconciliation follows.
        controller.current = new AbortController();
        await reconcile(receipt);
        if (active.current && terminalError && pendingRef.current) {
          const failure = terminalError as Event & { event: 'error' };
          setStatus(failure.status === 429
            ? failure.category === 'generation_budget'
              ? 'The monthly generation allowance is used up. Reading and evidence remain available; the allowance resets next UTC month.'
              : `Generation is busy or limited. Wait${failure.retry_after ? ` at least ${failure.retry_after} seconds` : ''}, then check before retrying.`
            : 'The answer was not confirmed saved. Your question is kept. Check saved answer before retrying.');
        }
      }
      lock.current = false;
    }
  }

  async function stageAction(route: string, body: object) {
    if (lock.current || pendingRef.current || busy || moving) return;
    lock.current = true;
    setMoving(true);
    setProjectUncertain(true);
    setStatus('Checking saved project…');
    try {
      await verify();
      const response = await fetch(`${path}/project/${route}`, {
        method: 'POST', credentials: 'same-origin', cache: 'no-store', signal: controller.current.signal,
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      await verify();
      if ([401, 403].includes(response.status)) { expired(); return; }
      // Even an ambiguous POST is reconciled by reads; decisions are never automatically replayed.
      await refresh();
      if (active.current) {
        setProjectUncertain(false);
        setStatus(response.ok ? 'Saved project updated.' : 'That action is no longer available. Saved project refreshed.');
      }
    } catch { if (active.current) setStatus('Could not verify the project action. Refresh saved project before continuing.'); }
    finally { if (active.current) setMoving(false); lock.current = false; }
  }

  async function refreshProject() {
    setMoving(true);
    try { await verify(); await refresh(); if (active.current) { setProjectUncertain(false); setStatus('Saved project refreshed.'); } }
    catch { if (active.current) setStatus('Could not refresh saved project. Try again when connected.'); }
    finally { if (active.current) setMoving(false); }
  }

  async function download() {
    if (!evidence) return;
    setDownloadError('');
    try {
      await verify();
      const response = await fetch(`${path}/messages/${encodeURIComponent(evidence.message)}/citations/${encodeURIComponent(evidence.citation.source_id)}/content`, {
        credentials: 'same-origin', cache: 'no-store', signal: controller.current.signal,
      });
      if (!response.ok) throw new ApiError(response.status);
      const blob = await response.blob();
      await verify();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url; anchor.download = evidence.citation.title; anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch { if (active.current) setDownloadError('This source could not be downloaded. It may have been removed; try again or open Streamlit.'); }
  }

  useEffect(() => {
    active.current = true;
    if (initial.current.pending) void reconcile(initial.current.pending);
    return () => { active.current = false; controller.current.abort(); };
  }, []);
  useEffect(() => { if (evidence) evidenceHeading.current?.focus({ preventScroll: true }); }, [evidence]);

  return <section aria-label="Saved conversation" className="conversation">
    <div className="conversation-chat">
    <h2>{page.notebook.name}</h2>
    <p className="supporting active-stage">Project stage: {project.stages.find(stage => stage.id === project.current_stage)?.label}</p>
    <button ref={pathToggle} className="path-toggle mobile-only" aria-expanded={pathOpen} aria-controls="project-path" onClick={() => {
      setPathOpen(value => !value);
      if (!pathOpen) window.requestAnimationFrame(() => document.getElementById('path-heading')?.focus({ preventScroll: true }));
    }}>Thinking Path{project.pending ? ' · decision pending' : ''}</button>
    <Sources owner={owner} thread={page.notebook.id} expired={expired} uncertain={setSourceUncertain} opened={() => setPathOpen(false)}/>
    <fieldset className="intent-switch" disabled={watching || checking || moving || !!pending}>
      <legend>What would you like to work on?</legend>
      {(['lecture', 'project'] as const).map(value => <label key={value}><input type="radio" name="intent" value={value} checked={intent === value} onChange={() => {
        intentRef.current = value; setIntent(value); remember(textRef.current, pendingRef.current);
      }}/>{value === 'lecture' ? 'Ask about a lecture' : 'Develop my project'}</label>)}
    </fieldset>
    {intent === 'lecture' ? <p className="supporting">Answers use available course evidence and selected notebook sources; gaps are stated. Lecture help leaves your project stage unchanged.</p> : null}
    {projectUncertain ? <p role="alert">Check saved project before another action. <button disabled={moving || busy} onClick={() => void refreshProject()}>Refresh saved project</button></p> : null}
    <p className="supporting">{page.messages.length} of {page.total_count} saved messages.</p>
    {page.next_cursor ? <button disabled={busy} onClick={() => {
      const height = document.documentElement.scrollHeight;
      const scroll = window.scrollY;
      void loadEarlier().then(() => window.requestAnimationFrame(() => window.scrollTo(0, scroll + document.documentElement.scrollHeight - height)));
    }}>Load earlier messages</button> : null}
    {page.messages.length === 0 ? <p>No saved messages yet. Write your first question or project contribution below.</p> : null}
    {page.messages.map(message => <article className={`message ${message.role === 'user' ? 'student' : 'coach'}`} key={message.id}>
      <h3>{message.role === 'user' ? 'You' : 'Coach'}</h3>
      <div className="message-content">{message.content}</div>
      {message.citations.length ? <div className="citations" aria-label="Supporting evidence">{message.citations.map(citation =>
        <button key={`${citation.label}:${citation.source_id}`} onClick={event => {
          returnScroll.current = window.scrollY; citationButton.current = event.currentTarget;
          setDownloadError(''); setEvidence({ citation, message: message.id });
        }}>{citation.label} · {citation.title}</button>)}</div> : null}
    </article>)}
    {evidence ? <aside className="evidence" aria-label="Cited evidence">
      <div className="evidence-heading"><h3 ref={evidenceHeading} tabIndex={-1}>{evidence.citation.label} · {evidence.citation.title}</h3>
        <button onClick={() => {
          setEvidence(null); citationButton.current?.focus({ preventScroll: true }); window.scrollTo(0, returnScroll.current);
        }}>Return to answer</button></div>
      <p className="supporting">Excerpt saved with this answer</p>
      <blockquote>{evidence.citation.excerpt || 'No excerpt was saved. Download the original to inspect it.'}</blockquote>
      <button onClick={() => void download()}>Download original source</button>
      {downloadError ? <p role="alert">{downloadError}</p> : null}
    </aside> : null}
    <form className="composer" onSubmit={event => { event.preventDefault(); void send(); }}>
      <label htmlFor="lecture-question">{intent === 'lecture' ? 'Your lecture question' : 'Your project contribution'}</label>
      <textarea ref={composer} id="lecture-question" value={text} maxLength={12000} rows={3}
        placeholder="What would you like to understand?" onChange={event => remember(event.target.value, pendingRef.current)}/>
      <div className="composer-actions"><span className="supporting">{intent === 'lecture' ? 'Lecture help · project stages unchanged' : `Project coaching · ${project.stages.find(stage => stage.id === project.current_stage)?.label}`}</span>
        <button className="primary" type="submit" disabled={watching || checking || busy || moving || sourceUncertain || projectUncertain || !!pending || !text.trim()}>{intent === 'lecture' ? 'Send question' : 'Send project work'}</button></div>
    </form>
    {storageError ? <p role="alert">Tab storage is unavailable. Keep a copy of your draft before reloading.</p> : null}
    <div className="turn-status" role="status" aria-live="polite">{status}</div>
    {preview ? <article className="message preview"><h3>Coach · unsaved preview</h3><div className="message-content">{preview}</div></article> : null}
    {watching ? <button onClick={() => { controller.current.abort(); }}>Stop watching</button> : null}
    {pending && !watching ? <div className="recovery-actions">
      <p className="supporting">Pending question: {pending.text}</p>
      <button disabled={checking || busy} onClick={() => void reconcile(pending)}>Check saved answer</button>
      <button disabled={checking || busy || checkedKey !== pending.key} onClick={() => void send(true)}>Retry same question</button>
    </div> : null}
    </div>
    <aside id="project-path" className={`project-panel ${pathOpen ? 'path-open' : ''}`} aria-label="Project Thinking Path">
      <button className="mobile-only" onClick={() => { setPathOpen(false); pathToggle.current?.focus({ preventScroll: true }); }}>Return to chat</button>
      <ThinkingPath project={project} disabled={watching || checking || busy || moving || !!pending || projectUncertain} act={stageAction}/>
    </aside>
  </section>;
}
