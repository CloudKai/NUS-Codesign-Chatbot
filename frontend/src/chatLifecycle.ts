/** Explicit chat turn lifecycle: request, owner identity, save and recovery states.
 *
 * One state machine owns a coach turn from send to resolution. The phases are
 * mutually exclusive, replacing the previous independent booleans (watching,
 * canStop, checking) that could encode contradictory combinations:
 *
 * - `idle` — no turn in flight; a pending receipt may still await recovery.
 * - `requesting` — the stream request is issued but not yet acknowledged.
 * - `streaming` — `started` acknowledged; the student may stop generation.
 * - `saving` — the saving phase has begun (or the terminal event arrived);
 *   stopping can no longer cancel the turn.
 * - `checking` — a read-only reconciliation is in flight.
 *
 * Recovery metadata stays separate: a `pending` receipt (an unresolved request
 * kept for read-only recovery) and `checkedKey` (the key whose check completed
 * without finding a saved reply). A check that finds nothing saved frees the
 * composer automatically; there are no recovery buttons and no in-progress
 * words — the bouncing progress dots carry the state.
 */
import { useEffect, useRef, useState, type RefObject } from 'react';
import { ApiError, currentSession, get } from './api';
import { createReplyPreview } from './replyPreview';
import { useChatProgress } from './ChatProgress';
import { newRequestKey } from './requestKey';
import { REPLY_DELTAS_HEADER, isTurn, readStream, type Event } from './stream';

export type Intent = 'improve' | 'project';
export interface Attachment { id: string; title: string }
/** One coach request identity, kept for read-only recovery under the same key. */
export interface Receipt { key: string; text: string; intent?: Intent; message?: string; attachments?: Attachment[]; legacyLectureRoute?: boolean }

/** Mutually exclusive request phases for one coach turn. */
type Turn =
  | { phase: 'idle' }
  | { phase: 'requesting'; key: string }
  | { phase: 'streaming'; key: string; canStop: boolean }
  | { phase: 'saving'; key: string }
  | { phase: 'checking'; key: string };

/** One selected canvas node carried into the next coaching turn. */
export interface CanvasSelection {
  canvasId: string; revision: number; nodeIds: string[]; label: string;
  /** discuss (default) or an explicit draft-synthesis request. */
  purpose?: 'discuss' | 'draft';
}

/** One artifact passage (or whole document) carried into the next coaching turn. */
export interface ArtifactSelection {
  artifactId: string; revision: number; paragraph: number | null; label: string;
}

/** The composer draft facets the lifecycle reads and persists through `remember`. */
export interface DraftControl {
  text: RefObject<string>;
  intent: RefObject<Intent | undefined>;
  attachments: Attachment[];
  remember: (text: string, pending: Receipt | null, attachments?: Attachment[]) => void;
}

export interface ChatLifecycleParams {
  threadId: string;
  owner: string;
  expired: () => void;
  refresh: () => Promise<void>;
  composer: RefObject<HTMLTextAreaElement | null>;
  busy: boolean;
  moving: boolean;
  externalBlocked: boolean;
  feedbackBusy: boolean;
  projectUncertain: boolean;
  stickToLatest: RefObject<boolean>;
  draft: DraftControl;
  /** A receipt restored from tab storage that still needs its first check. */
  initialPending: Receipt | null;
  /** Selected canvas nodes attached once to the next send, then cleared. */
  canvasSelection?: { current: CanvasSelection | null; clear: () => void };
  /** Selected artifact passage attached once to the next send, then cleared. */
  artifactSelection?: { current: ArtifactSelection | null; clear: () => void };
}

/** Run one chat lifecycle for this owner and thread. */
export function useChatLifecycle({
  threadId, owner, expired, refresh, composer, busy, moving, externalBlocked,
  feedbackBusy, projectUncertain, stickToLatest, draft, initialPending, canvasSelection, artifactSelection,
}: ChatLifecycleParams) {
  const [turn, setTurn] = useState<Turn>({ phase: 'idle' });
  const [stopping, setStopping] = useState(false);
  const [checkedKey, setCheckedKey] = useState('');
  const [status, setStatus] = useState('');
  const [preview, setPreview] = useState('');
  const [pending, setPending] = useState<Receipt | null>(initialPending);
  const progress = useChatProgress();

  const active = useRef(true);
  const lock = useRef(false);
  const controller = useRef(new AbortController());
  const pendingRef = useRef(pending);
  pendingRef.current = pending;

  // Derived request states. Recovery is pending + checkedKey, not a phase.
  const watching = turn.phase === 'requesting' || turn.phase === 'streaming' || turn.phase === 'saving';
  const canStop = turn.phase === 'streaming' && turn.canStop;
  const checking = turn.phase === 'checking';
  const path = `/api/v1/reader/threads/${encodeURIComponent(threadId)}`;

  async function verify() {
    const session = await currentSession(controller.current.signal);
    if (!active.current) throw new Error('View closed');
    if (session.owner_id !== owner) { expired(); throw new Error('Session changed'); }
  }

  /** Read-only reconciliation: adopt a saved reply or arm retry/discard for the same key. */
  async function reconcile(receipt: Receipt): Promise<'saved' | 'unchecked' | 'error'> {
    setTurn({ phase: 'checking', key: receipt.key });
    setCheckedKey('');
    setPreview('');
    try {
      await verify();
      const saved = await get<unknown>(`${path}/coach-turn?${new URLSearchParams({ idempotency_key: receipt.key })}`, controller.current.signal);
      await verify();
      if (saved !== null && !isTurn(saved)) throw new Error('Malformed saved reply');
      if (saved) {
        progress.saved();
        draft.remember(!receipt.message && draft.text.current === receipt.text ? '' : draft.text.current, null, receipt.message ? draft.attachments : []);
        setStatus('Your answer is ready.');
        await refresh();
        if (receipt.message) composer.current?.focus({ preventScroll: true });
        return 'saved';
      }
      progress.clear();
      // Wordless recovery: a check that found nothing saved returns the question
      // to the composer automatically, so no recovery buttons are needed.
      draft.remember(receipt.message
        ? (draft.text.current.trim() ? `${draft.text.current}\n\n${receipt.text}` : receipt.text)
        : draft.text.current, null);
      setStatus('');
      return 'unchecked';
    } catch (error) {
      if (!active.current) return 'error';
      progress.clear();
      if (error instanceof ApiError && [401, 403].includes(error.status)) expired();
      else setStatus('We couldn’t check for your reply. Your question is kept. Check again when you’re connected.');
      return 'error';
    } finally { if (active.current) setTurn({ phase: 'idle' }); }
  }

  /** One small reload control: check the saved reply, then retry the same question only when nothing was saved. */
  async function stopGeneration() {
    const receipt = pendingRef.current;
    if (!receipt || !canStop || stopping) return;
    setStopping(true);
    try {
      const response = await fetch(`${path}/coach-turn/stop`, {
        method: 'POST', credentials: 'same-origin', cache: 'no-store',
        signal: controller.current.signal, headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ idempotency_key: receipt.key }),
      });
      if (!active.current || pendingRef.current?.key !== receipt.key) return;
      if ([401, 403].includes(response.status)) { expired(); return; }
      if (!response.ok) throw new ApiError(response.status);
      const result: { status: 'stopping' | 'saving' | 'finished' } = await response.json();
      if (active.current && pendingRef.current?.key === receipt.key && result.status === 'stopping') setStatus('Stopping generation…');
    } catch {
      if (active.current && pendingRef.current?.key === receipt.key) {
        setStatus('Could not stop generation. Try again.');
        setStopping(false);
      }
    }
  }

  async function send(retry = false, revision?: Receipt) {
    if (lock.current || busy || moving || externalBlocked || feedbackBusy || projectUncertain || (!retry && (pendingRef.current || (!revision && !draft.text.current.trim())))) return;
    if (retry && checkedKey !== pendingRef.current?.key) return;
    lock.current = true;
    stickToLatest.current = true;
    const receipt = retry ? pendingRef.current! : revision || { key: newRequestKey(), text: draft.text.current, intent: draft.intent.current, attachments: draft.attachments };
    if (!receipt) { lock.current = false; return; }
    draft.remember(draft.text.current, receipt);
    progress.start();
    setStopping(false);
    setPreview('');
    setStatus('Sending your message…');
    setTurn({ phase: 'requesting', key: receipt.key });
    controller.current.abort();
    controller.current = new AbortController();
    const paint = createReplyPreview(value => { if (active.current) setPreview(value); }, controller.current.signal);
    let terminalError: Event & { event: 'error' } | null = null;
    const completion = { text: '' };
    try {
      await verify();
      const modeRoute = receipt.legacyLectureRoute ? 'lecture' : receipt.intent ?? 'improve';
      const response = await fetch(receipt.message ? `${path}/messages/${encodeURIComponent(receipt.message)}/revise/stream` : `${path}/${modeRoute}/stream`, {
        method: 'POST', credentials: 'same-origin', cache: 'no-store', signal: controller.current.signal,
        headers: { 'Content-Type': 'application/json', ...REPLY_DELTAS_HEADER },
        body: JSON.stringify(receipt.message ? { content: receipt.text, idempotency_key: receipt.key }
          : { student_message: receipt.text, idempotency_key: receipt.key, attachment_source_ids: receipt.attachments?.map(file => file.id) ?? [],
              ...(canvasSelection?.current ? { canvas_selection: { canvas_id: canvasSelection.current.canvasId, revision: canvasSelection.current.revision, node_ids: canvasSelection.current.nodeIds, ...(canvasSelection.current.purpose === 'draft' ? { purpose: 'draft' } : {}) } } : {}),
              ...(artifactSelection?.current ? { artifact_selection: { artifact_id: artifactSelection.current.artifactId, revision: artifactSelection.current.revision, paragraph: artifactSelection.current.paragraph } } : {}) }),
      });
      // The selections ride exactly one send; the next question starts clean.
      if (!receipt.message) { canvasSelection?.clear(); artifactSelection?.clear(); }
      if (!response.ok) throw new ApiError(response.status);
      await readStream(response, threadId, receipt.key, event => {
        if (!active.current) return;
        if (event.event === 'started') { setTurn({ phase: 'streaming', key: receipt.key, canStop: true }); setStatus('Reading your message…'); }
        if (event.event === 'status' && event.phase === 'saving') { setTurn({ phase: 'saving', key: receipt.key }); progress.saving(); }
        if (event.event === 'status') setStatus(({ queued: 'Waiting for an available coaching slot…', retrieving: 'Looking through your sources…', thinking: 'Preparing your reply…', saving: 'Saving…' })[event.phase]);
        // Deltas are unvalidated and unsaved: they only ever feed the preview, never saved messages.
        if (event.event === 'reply_delta') { progress.writing(); paint.append(event.text); setStatus('Writing your reply…'); }
        if (event.event === 'reply_discard') { progress.discard(); paint.discard(); setStatus('Preparing your reply…'); }
        if (event.event === 'reply_ready') { setTurn({ phase: 'saving', key: receipt.key }); progress.saving(); setStatus('Saving…'); }
        if (event.event === 'done') { setTurn({ phase: 'saving', key: receipt.key }); progress.saved(); completion.text = event.turn.response_text; }
        if (event.event === 'error') { progress.clear(); terminalError = event; paint.discard(); }
      });
      if (completion.text) await paint.finish(completion.text);
    } catch (error) {
      progress.clear();
      if (active.current && error instanceof ApiError && [401, 403].includes(error.status)) { expired(); return; }
    } finally {
      paint.dispose();
      if (active.current) {
        setPreview('');
        setStopping(false);
        // A terminal cancellation was confirmed by the worker. Other outcomes use read-only recovery.
        controller.current = new AbortController();
        const failure = terminalError as (Event & { event: 'error' }) | null;
        if (failure?.category === 'cancelled') {
          progress.clear();
          setTurn({ phase: 'idle' });
          if (receipt.message || draft.text.current !== receipt.text) {
            setCheckedKey(receipt.key);
            if (receipt.message) await refresh();
          } else {
            draft.remember(receipt.text, null);
          }
          setStatus('Generation stopped. Your prompt is kept.');
        } else {
          await reconcile(receipt);
        }
        if (active.current && failure && failure.category !== 'cancelled') {
          setStatus(failure.status === 429
            ? failure.category === 'generation_budget'
              ? 'This month’s coach allowance is used up. You can still read your work and sources. It resets next month.'
              : `The coach is busy right now. Wait${failure.retry_after ? ` at least ${failure.retry_after} seconds` : ''}, then send again.`
            : 'We couldn’t reach the coach just now. Your message is back in the composer — try again in a moment.');
        }
      }
      lock.current = false;
    }
  }

  useEffect(() => {
    active.current = true;
    if (initialPending) void reconcile(initialPending);
    return () => { active.current = false; controller.current.abort(); };
  }, []);

  return {
    /** Owner/request identity shared with the other conversation operations. */
    active, controller, lock, verify,
    /** Derived request states with mutually exclusive phases underneath. */
    watching, canStop, checking, stopping,
    /** Recovery metadata: the unresolved receipt and its completed-check key. */
    pending, setPending, pendingRef, checkedKey, setCheckedKey,
    /** Presentation state fed by lifecycle events. */
    status, setStatus, preview, progress,
    /** Operations. */
    send, reconcile, stopGeneration,
  };
}
