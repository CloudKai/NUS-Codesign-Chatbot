/** Lecture composer, exact-request reconciliation and saved citation inspection. */
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { ApiError, currentSession, get, type Page, type Project } from './api';
import { ThinkingPath } from './ThinkingPath';
import { Icon } from './Icon';
import { CoachText } from './CoachText';
import { ReasoningPrompts } from './ReasoningPrompts';
import { isTurn, readStream, type Citation, type Event } from './stream';

type Intent = 'lecture' | 'project';
interface Attachment { id: string; title: string }
interface Receipt { key: string; text: string; intent?: Intent; message?: string; attachments?: Attachment[] }
interface Draft { text: string; pending: Receipt | null; intent?: Intent; attachments?: Attachment[] }
const empty: Draft = { text: '', pending: null };

/** Read only this owner's tab-scoped unsent text and recovery identity; never store replies. */
function restore(key: string): Draft {
  try {
    const value = JSON.parse(sessionStorage.getItem(key) || 'null');
    if (!value || typeof value.text !== 'string') return empty;
    const pending = value.pending;
    return { text: value.text, intent: value.intent === 'project' ? 'project' : 'lecture',
      attachments: Array.isArray(value.attachments) ? value.attachments : [],
      pending: pending && typeof pending.key === 'string' && typeof pending.text === 'string' ? pending : null };
  } catch { return empty; }
}

/** Keep draft, focus and loaded transcript stable during progress and evidence inspection. */
export function Conversation({ page, project, owner, refresh, expired, busy, loadEarlier, externalBlocked, activity, onHelp, preferredIntent, showStarters, reduceMotion, onboardingRequest, displayTitle = page.notebook.name }: {
  page: Page; project: Project; owner: string; refresh: () => Promise<void>; expired: () => void;
  onHelp: () => void; preferredIntent: Intent; showStarters: boolean; reduceMotion: boolean; onboardingRequest: number;
  externalBlocked: boolean; activity: (value: boolean) => void;
  busy: boolean; loadEarlier: () => Promise<void>;
  displayTitle?: string;
}) {
  const storageKey = `codesign-lecture:${owner}:${page.notebook.id}`;
  const initial = useRef(restore(storageKey));
  const [mode, setIntent] = useState<Intent | undefined>(initial.current.intent ?? (page.total_count ? 'lecture' : undefined));
  const intent = mode ?? preferredIntent;
  const [pathOpen, setPathOpen] = useState(false);
  const [dismissedRequest, setDismissedRequest] = useState<number | null>(null);
  const transcript = useRef<HTMLDivElement>(null);
  const stickToLatest = useRef(true);
  const pathToggle = useRef<HTMLButtonElement>(null);
  const reviewPanel = useRef<HTMLDialogElement>(null);
  useLayoutEffect(() => {
    const panel = reviewPanel.current;
    if (!panel) return;
    const compact = window.matchMedia('(max-width: 1023px)');
    const showReview = () => {
      panel.close();
      if (compact.matches) panel.showModal();
      else panel.show();
      panel.querySelector<HTMLElement>('#review-heading')?.focus({ preventScroll: true });
    };
    showReview();
    compact.addEventListener('change', showReview);
    return () => {
      compact.removeEventListener('change', showReview);
      panel.close();
    };
  }, [pathOpen]);
  const [moving, setMoving] = useState(false);
  const [projectUncertain, setProjectUncertain] = useState(false);
  const intentRef = useRef(intent);
  intentRef.current = intent;
  const [text, setText] = useState(initial.current.text);
  const [attachments, setAttachments] = useState<Attachment[]>(initial.current.attachments ?? []);
  const [uploading, setUploading] = useState(false);
  const attachmentInput = useRef<HTMLInputElement>(null);
  const [pending, setPending] = useState<Receipt | null>(initial.current.pending);
  const pendingRef = useRef(pending);
  const textRef = useRef(text);
  const [watching, setWatching] = useState(false);
  const [checking, setChecking] = useState(false);
  const [checkedKey, setCheckedKey] = useState('');
  const [status, setStatus] = useState('');
  const [reviewStatus, setReviewStatus] = useState('');
  const [preview, setPreview] = useState('');
  const [edit, setEdit] = useState<{ id: string; text: string } | null>(null);
  const [feedbackBusy, setFeedbackBusy] = useState(false);
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

  function remember(nextText: string, nextPending: Receipt | null, nextAttachments = attachments) {
    setIntent(intentRef.current);
    textRef.current = nextText;
    pendingRef.current = nextPending;
    setText(nextText);
    setPending(nextPending);
    setAttachments(nextAttachments);
    try { sessionStorage.setItem(storageKey, JSON.stringify({ text: nextText, pending: nextPending, intent: intentRef.current, attachments: nextAttachments })); }
    catch { setStorageError(true); }
  }

  async function verify() {
    const session = await currentSession(controller.current.signal);
    if (!active.current) throw new Error('View closed');
    if (session.owner_id !== owner) { expired(); throw new Error('Session changed'); }
  }

  async function uploadAttachments(files: File[]) {
    if (!files.length || lock.current || pendingRef.current) return;
    if (attachments.length + files.length > 5) { setStatus('Attach up to five files per message.'); return; }
    lock.current = true;
    setUploading(true);
    setStatus('Checking files…');
    try {
      await verify();
      const data = new FormData();
      files.forEach(file => data.append('files', file));
      const response = await fetch(`${path}/attachments`, {
        method: 'POST', credentials: 'same-origin', cache: 'no-store', body: data, signal: controller.current.signal,
      });
      if (!response.ok) {
        if ([401, 403].includes(response.status)) { expired(); return; }
        const detail = response.status === 422 ? (await response.json()).detail : '';
        setStatus(typeof detail === 'string' && detail
          ? detail : 'Could not attach those files. Check the Library and try again.');
        return;
      }
      const uploaded: Attachment[] = await response.json();
      await verify();
      remember(textRef.current, null, [...attachments, ...uploaded]);
      setStatus('Files attached and saved in your Library.');
    } catch {
      if (active.current) setStatus('Could not confirm the upload. Check the Library before retrying.');
    } finally {
      lock.current = false;
      if (active.current) setUploading(false);
    }
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
        remember(!receipt.message && textRef.current === receipt.text ? '' : textRef.current, null, receipt.message ? attachments : []);
        setStatus('Answer saved.');
        await refresh();
        if (receipt.message) composer.current?.focus({ preventScroll: true });
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

  async function send(retry = false, revision?: Receipt) {
    if (lock.current || busy || moving || externalBlocked || feedbackBusy || projectUncertain || (!retry && (pendingRef.current || (!revision && !textRef.current.trim())))) return;
    if (retry && checkedKey !== pendingRef.current?.key) return;
    lock.current = true;
    stickToLatest.current = true;
    const receipt = retry ? pendingRef.current! : revision || { key: crypto.randomUUID(), text: textRef.current, intent: intentRef.current, attachments };
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
      const response = await fetch(receipt.message ? `${path}/messages/${encodeURIComponent(receipt.message)}/revise` : `${path}/${receipt.intent || 'lecture'}/stream`, {
        method: 'POST', credentials: 'same-origin', cache: 'no-store', signal: controller.current.signal,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(receipt.message ? { content: receipt.text, idempotency_key: receipt.key }
          : { student_message: receipt.text, idempotency_key: receipt.key, attachment_source_ids: receipt.attachments?.map(file => file.id) ?? [] }),
      });
      if (!response.ok) throw new ApiError(response.status);
      if (receipt.message) {
        if (!isTurn(await response.json())) throw new Error('Malformed saved edit');
      } else await readStream(response, page.notebook.id, receipt.key, event => {
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
    if (lock.current || pendingRef.current || busy || moving || externalBlocked || feedbackBusy) return;
    lock.current = true;
    setMoving(true);
    setProjectUncertain(true);
    setReviewStatus('Checking saved project…');
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
        setReviewStatus(response.ok ? 'Saved project updated.' : 'That action is no longer available. Saved project refreshed.');
      }
    } catch { if (active.current) setReviewStatus('Could not verify the project action. Refresh saved project before continuing.'); }
    finally { if (active.current) setMoving(false); lock.current = false; }
  }

  async function refreshProject() {
    setMoving(true);
    try { await verify(); await refresh(); if (active.current) { setProjectUncertain(false); setReviewStatus('Saved project refreshed.'); } }
    catch { if (active.current) setReviewStatus('Could not refresh saved project. Try again when connected.'); }
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
    } catch (error) {
      if (!active.current) return;
      setDownloadError(error instanceof ApiError && error.status === 404
        ? 'Source unavailable. The saved citation is still part of this answer.'
        : 'Could not download this source. Check your connection and try again.');
    }
  }

  async function rate(message: string, kind: 'useful' | 'not_useful') {
    if (lock.current || feedbackBusy || externalBlocked) return;
    lock.current = true; setFeedbackBusy(true);
    try {
      await verify();
      const response = await fetch(`${path}/messages/${encodeURIComponent(message)}/learning-signal`, {
        method: 'POST', credentials: 'same-origin', cache: 'no-store', signal: controller.current.signal,
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ kind }),
      });
      await verify();
      if ([401, 403].includes(response.status)) { expired(); return; }
      await refresh(); setStatus(response.ok ? 'Feedback saved.' : 'Feedback was not saved. Latest saved answer refreshed; try again.');
    } catch { if (active.current) setStatus('Could not verify feedback. Refresh saved project to read the latest saved answer before trying again.'); }
    finally { lock.current = false; if (active.current) setFeedbackBusy(false); }
  }
  useEffect(() => { activity(watching || checking || moving || uploading || !!pending || projectUncertain || feedbackBusy); }, [watching, checking, moving, uploading, pending, projectUncertain, feedbackBusy]);
  const editIndex = pending?.message ? page.messages.findIndex(message => message.id === pending.message) : -1;
  const visibleMessages = editIndex >= 0 ? page.messages.slice(0, editIndex) : page.messages;

  useEffect(() => {
    active.current = true;
    if (initial.current.pending) void reconcile(initial.current.pending);
    return () => { active.current = false; controller.current.abort(); };
  }, []);
  useEffect(() => { if (evidence) evidenceHeading.current?.focus({ preventScroll: true }); }, [evidence]);

  useEffect(() => {
    if (stickToLatest.current && transcript.current) transcript.current.scrollTop = transcript.current.scrollHeight;
  }, [page.messages, preview, watching]);

  function closePath() {
    setPathOpen(false);
    window.requestAnimationFrame(() => pathToggle.current?.focus({ preventScroll: true }));
  }

  const done = project.stages.filter(stage => stage.completed).length;
  const isEmpty = page.messages.length === 0 && !watching && !pending;
  const choosePrompt = (prompt: string) => {
    remember(textRef.current.trim() ? `${textRef.current}\n\n${prompt}` : prompt, pendingRef.current);
    composer.current?.focus({ preventScroll: true });
  };

  function startDesignChat() {
    setPathOpen(false);
    if (!pendingRef.current) {
      intentRef.current = 'project';
      setIntent('project');
      remember(textRef.current, null);
    }
    window.requestAnimationFrame(() => composer.current?.focus({ preventScroll: true }));
  }

  return <section aria-label="Saved conversation" className={`conversation ${pathOpen ? 'review-open' : ''}`}>
    <header className="chat-heading">
      <h2 title={displayTitle}>{displayTitle}</h2>
      <button ref={pathToggle} className="path-toggle" aria-haspopup="dialog" aria-expanded={pathOpen}
        aria-description={project.pending ? 'Stage decision pending' : undefined}
        aria-controls={pathOpen ? 'project-review' : undefined} onClick={() => pathOpen ? closePath() : setPathOpen(true)}>
        <Icon name="path"/> Review{project.pending ? <span className="decision-dot" aria-hidden="true"/> : null}
      </button>
    </header>
    <div className="conversation-chat">
    <div className={`transcript ${isEmpty ? 'transcript-empty' : ''}`} ref={transcript} onScroll={event => {
      const panel = event.currentTarget;
      stickToLatest.current = panel.scrollHeight - panel.scrollTop - panel.clientHeight < 80;
    }}>
    <div className="chat-column">
    {projectUncertain && !pathOpen ? <p role="alert">Check saved project before another action. <button disabled={moving || busy} onClick={() => void refreshProject()}>Refresh saved project</button></p> : null}

    {page.next_cursor ? <button disabled={busy} onClick={() => {
      const panel = transcript.current;
      if (!panel) return;
      const height = panel.scrollHeight;
      const scroll = panel.scrollTop;
      stickToLatest.current = false;
      void loadEarlier().then(() => window.requestAnimationFrame(() => { panel.scrollTop = scroll + panel.scrollHeight - height; }));
    }}>Load earlier messages</button> : null}
    {isEmpty ? <div className="chat-welcome"><span className="welcome-mark"><Icon name="spark"/></span>
      <h1>Make room for a better question.</h1><p>Bring a half-formed thought. We’ll work through it together.</p>
      {showStarters ? <ReasoningPrompts disabled={checking || moving || externalBlocked} onChoose={choosePrompt}/> : null}
      {dismissedRequest !== onboardingRequest && done === 0 ? <section className="onboarding">
        <button className="icon-button dismiss-onboarding" aria-label="Dismiss getting started" title="Dismiss getting started" onClick={() => setDismissedRequest(onboardingRequest)}><Icon name="close"/></button>
        <h2>Start your design project</h2>
        <p>Explore a problem, test an idea, or get help with your next step.</p>
        <div className="onboarding-actions"><button className="primary" onClick={startDesignChat}>Start exploring <Icon name="chevronRight"/></button><button onClick={onHelp}>How it works</button></div>
      </section> : null}
    </div> : null}
    {visibleMessages.map(message => <article className={`message ${message.role === 'user' ? 'student' : 'coach'}`} key={message.id}>
      <h3>{message.role === 'user' ? 'You' : 'Coach'}</h3>
      {message.role === 'user' ? <div className="message-content">{message.content}</div> : <CoachText text={message.content}/>}
      <div className="message-actions">
        <button aria-label={message.role === 'user' ? 'Copy your message' : 'Copy answer'} title="Copy" onClick={() => { void navigator.clipboard.writeText(message.content).then(() => setStatus('Message copied.')).catch(() => setStatus('Could not copy. Select the message text to copy it.')); }}><Icon name="copy"/></button>
        {message.role === 'user' ? <button aria-label="Edit message" title="Edit message" disabled={watching || checking || moving || !!pending || externalBlocked || projectUncertain} id={`edit-trigger-${message.id}`} onClick={() => setEdit({ id: message.id, text: message.content })}><Icon name="edit"/></button> : null}
        {message.feedback_available ? <div role="group" aria-label="Was this answer useful?">
          {(['useful', 'not_useful'] as const).map(kind => <button key={kind} aria-label={kind === 'useful' ? 'Useful' : 'Not useful'} title={kind === 'useful' ? 'Useful' : 'Not useful'} aria-pressed={message.rating === kind} disabled={feedbackBusy || watching || checking || !!pending || externalBlocked} onClick={() => void rate(message.id, kind)}><Icon name={kind === 'useful' ? 'up' : 'down'}/></button>)}
        </div> : null}
      </div>
      {edit?.id === message.id ? <form className="message-edit" onSubmit={event => {
        event.preventDefault(); const receipt = { key: crypto.randomUUID(), text: edit.text, message: edit.id }; setEdit(null); void send(false, receipt);
      }}>
        <label htmlFor={`edit-${message.id}`}>Revise your message</label>
        <textarea autoFocus id={`edit-${message.id}`} value={edit.text} maxLength={12000} onChange={event => setEdit({ ...edit, text: event.target.value })}/>
        <p>Saving replaces this message and the replies after it in your active transcript, then asks the coach again. Your composer draft is kept.</p>
        <button type="button" onClick={() => { setEdit(null); document.getElementById(`edit-trigger-${message.id}`)?.focus({ preventScroll: true }); }}>Cancel edit</button>
        <button disabled={!edit.text.trim() || watching || checking || busy || moving || feedbackBusy || !!pending || externalBlocked || projectUncertain}>Confirm edit & ask again</button>
      </form> : null}
      {message.citations.length ? <div className="citations" aria-label="Supporting evidence">{message.citations.map(citation =>
        <button key={`${citation.label}:${citation.source_id}`} onClick={event => {
          returnScroll.current = transcript.current?.scrollTop || 0; citationButton.current = event.currentTarget;
          setDownloadError(''); setEvidence({ citation, message: message.id });
        }}>{citation.label} · {citation.title}</button>)}</div> : null}
    </article>)}
    {evidence ? <aside className="evidence" aria-label="Cited evidence">
      <div className="evidence-heading"><h3 ref={evidenceHeading} tabIndex={-1}>{evidence.citation.label} · {evidence.citation.title}</h3>
        <button onClick={() => {
          setEvidence(null); citationButton.current?.focus({ preventScroll: true }); transcript.current?.scrollTo(0, returnScroll.current);
        }}>Return to answer</button></div>
      <p className="supporting">Excerpt saved with this answer</p>
      <blockquote>{evidence.citation.excerpt || 'No excerpt was saved. Download the original to inspect it.'}</blockquote>
      <button onClick={() => void download()}>Download original source</button>
      {downloadError ? <p role="alert">{downloadError}</p> : null}
    </aside> : null}
    {preview && !reduceMotion ? <article className="message preview"><h3>Coach · unsaved preview</h3><CoachText text={preview}/></article> : null}
    {watching ? <button onClick={() => { controller.current.abort(); }}>Stop watching</button> : null}
    {pending && !watching ? <div className="recovery-actions">
      <p className="supporting">{pending.message ? 'Pending edit' : 'Pending question'}: {pending.text}</p>
      <button disabled={checking || busy} onClick={() => void reconcile(pending)}>Check saved answer</button>
      <button disabled={checking || busy || checkedKey !== pending.key} onClick={() => void send(true)}>Retry same question</button>
    </div> : null}
    </div></div>
    <div className="composer-dock"><div className="chat-column">
    <form className="composer" onSubmit={event => { event.preventDefault(); void send(); }}>
      <input ref={attachmentInput} hidden type="file" multiple aria-label="Attach files to your message" onChange={event => {
        const files = Array.from(event.target.files ?? []);
        event.target.value = '';
        void uploadAttachments(files);
      }}/>
      {attachments.length ? <ul className="composer-attachments" aria-label="Message attachments">
        {attachments.map(file => <li key={file.id}><Icon name="document"/><span title={file.title}>{file.title}</span>
          <button type="button" className="icon-button" disabled={uploading || !!pending} aria-label={`Remove attachment ${file.title}`}
            onClick={() => remember(textRef.current, null, attachments.filter(item => item.id !== file.id))}><Icon name="close"/></button></li>)}
      </ul> : null}
      <label className="sr-only" htmlFor="lecture-question">{intent === 'lecture' ? 'Your lecture question' : 'Your project contribution'}</label>
      <textarea ref={composer} id="lecture-question" value={text} maxLength={12000} rows={3} aria-describedby="composer-hint" onKeyDown={event => {
        if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
          event.preventDefault();
          event.currentTarget.form?.requestSubmit();
        }
      }}
        placeholder={intent === 'lecture' ? "Ask about a lecture, reading, or course concept…" : "Share an idea or ask a question…"} onChange={event => remember(event.target.value, pendingRef.current)}/>
      <div className="composer-actions">
        <button className="icon-button attach-button" type="button" aria-label="Attach files" title="Attach files" disabled={externalBlocked || uploading || watching || !!pending} onClick={() => attachmentInput.current?.click()}><Icon name="attach"/></button>
        <div className="composer-mode"><label className="sr-only" htmlFor="conversation-mode">Conversation mode</label><select id="conversation-mode" value={intent} disabled={watching || checking || moving || !!pending} title="Lecture help keeps your project stage unchanged. Project coaching develops your saved project." onChange={event => {
        const next = event.target.value as Intent; intentRef.current = next; setIntent(next); remember(textRef.current, pendingRef.current);
      }}><option value="lecture">Lecture help</option><option value="project">Design coaching</option></select></div>
        <span className="composer-hint" id="composer-hint">↵ send · ⇧ ↵ new line</span>
        <button className="primary send-button" aria-label="Send message" title="Send message" type="submit" disabled={watching || checking || busy || moving || projectUncertain || externalBlocked || uploading || feedbackBusy || !!pending || !text.trim()}><Icon name="arrow"/></button></div>
    </form>
    {storageError ? <p role="alert">Tab storage is unavailable. Keep a copy of your draft before reloading.</p> : null}
    <div className="turn-status" role="status" aria-live="polite">{status}</div>
    <p className="composer-note">Your coach can make mistakes. You decide what goes into your work.</p>
    </div></div>
    </div>
    {pathOpen ? <dialog ref={reviewPanel} id="project-review" className="project-panel" aria-labelledby="review-heading"
      onCancel={event => { event.preventDefault(); closePath(); }}
      onKeyDown={event => {
        if (event.key === 'Escape') {
          event.preventDefault();
          closePath();
        }
      }}>
      <ThinkingPath project={project}
        disabled={watching || checking || busy || moving || uploading || !!pending || projectUncertain || externalBlocked || feedbackBusy}
        act={stageAction} startInChat={startDesignChat} onClose={closePath} status={reviewStatus}>
        {projectUncertain && !moving ? <p className="review-recovery" role="alert">Check saved project before another action. <button disabled={busy} onClick={() => void refreshProject()}>Refresh saved project</button></p> : null}
      </ThinkingPath>
    </dialog> : null}
  </section>;
}
