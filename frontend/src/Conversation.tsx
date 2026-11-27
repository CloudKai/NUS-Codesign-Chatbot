/** Shared composer, exact-request reconciliation and saved citation inspection. */
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { ApiError, type Bookmarks, type ChatSummary, type Page, type Project } from './api';
import { setStar } from './api/client';
import { ChatToCanvasProposal } from './ChatToCanvas';
import { CanvasSuggestions } from './CanvasSuggestions';
import { CanvasDraftCard } from './CanvasDraftCard';
import { ArtifactFeedbackCard } from './ArtifactFeedback';
import type { CanvasSelection, ArtifactSelection } from './chatLifecycle';
import { selectStage, resolveTransition } from './api/client';
import { fetchConfirmedBookmarks, reconcileBookmarks } from './api/workspaceBookmarks';
import { reconcileProject } from './api/workspaceProject';
import { useQueryClient } from '@tanstack/react-query';
import { useChatLifecycle, type Attachment, type Intent, type Receipt } from './chatLifecycle';
import { newRequestKey } from './requestKey';
import { ThinkingPath, type ReviewTab } from './ThinkingPath';
import { REVIEW_LIMITS, ResizeHandle, useWorkspaceLayoutContext, applyLayoutStyle } from './workspaceLayout';
import { Icon } from './Icon';
import { CoachText } from './CoachText';
import { ReasoningPrompts } from './ReasoningPrompts';
import { hasProjectWork } from './StageStepper';
import { ModeSwitch } from './ModeSwitch';
import { StageRecommendation, MilestoneBanner, type Milestone } from './StageRecommendation';
import { StageStarters } from './StageStarters';
import { CoachCheckIn } from './CoachCheckIn';
import { chooseCheckIn, hintScaffold, feedbackToProjectScaffold, reflectionScaffold, type CheckIn } from './coachingContent';
import { citationText, type Citation } from './stream';

interface Draft { text: string; pending: Receipt | null; intent?: Intent; attachments?: Attachment[] }
const empty: Draft = { text: '', pending: null };

/** Read only this owner's tab-scoped unsent text and recovery identity; never store replies. */
function restore(key: string, legacyKey: string): Draft {
  try {
    const current = sessionStorage.getItem(key);
    const value = JSON.parse(current ?? sessionStorage.getItem(legacyKey) ?? 'null');
    if (!value || typeof value.text !== 'string') return empty;
    const pending = value.pending;
    const validPending = pending && typeof pending.key === 'string' && typeof pending.text === 'string';
    const intent = value.intent === 'project' ? 'project'
      : ['improve', 'lecture'].includes(value.intent) ? 'improve' : undefined;
    // Tab storage is user-mutable: every restored element is re-validated, never cast.
    const attachments = Array.isArray(value.attachments)
      ? value.attachments.filter((item: unknown): item is Attachment =>
          typeof item === 'object' && item !== null
          && 'id' in item && typeof item.id === 'string'
          && 'title' in item && typeof item.title === 'string')
      : [];
    return { text: value.text, intent,
      attachments,
      pending: validPending ? {
        key: pending.key, text: pending.text,
        message: typeof pending.message === 'string' ? pending.message : undefined,
        intent: pending.message ? intent : pending.intent === 'project' ? 'project' : 'improve',
        legacyLectureRoute: pending.legacyLectureRoute === true ||
          (!current && !pending.message && pending.intent !== 'project' && pending.intent !== 'improve'),
      } : null };
  } catch { return empty; }
}

/** Restore display choices only; private Review content must be fetched after owner verification. */
function restoreReview(key: string): { open: boolean; tab?: ReviewTab } {
  try {
    const value = JSON.parse(sessionStorage.getItem(key) || 'null');
    return { open: value?.open === true,
      tab: ['Progression', 'Summary', 'My work'].includes(value?.tab) ? value.tab : undefined };
  } catch { return { open: false }; }
}

/** Mode a saved chat reopens in: the student's latest turn when saved project data shows it, else the chat's kind of work. */
function savedIntent(page: Page, project: Project): Intent {
  const work = hasProjectWork(project);
  const projectIds = new Set(project.stages.flatMap(stage => [...stage.student_work, ...stage.feedback].map(item => item.message_id)));
  const last = page.messages.map(message => message.role).lastIndexOf('user');
  if (last >= 0) {
    const intent = page.messages[last].interaction_intent;
    if (intent === 'project_coaching') return 'project';
    if (intent === 'improve_design' || intent === 'lecture_help') return 'improve';
    const reply = page.messages[last + 1];
    if (projectIds.has(page.messages[last].id) || (reply && projectIds.has(reply.id))) return 'project';
    // Older unclassified turns fall back to the saved project projection.
    if (work && reply) return 'improve';
  }
  return work ? 'project' : 'improve';
}

/** Keep draft, focus and loaded transcript stable during progress and evidence inspection. */
export function Conversation({ page, project, owner, refresh, expired, busy, loadEarlier, locateMessage, externalBlocked, activity, onHelp: _onHelp, preferredIntent, showStarters, intentRequest, summary, startIntent, displayTitle = page.notebook.name, parent, seededBookmarks = null, canvasSelection, onCanvasSelectionConsumed, artifactSelection, onArtifactSelectionConsumed }: {
  page: Page; project: Project; owner: string; refresh: () => Promise<void>; expired: () => void;
  onHelp: () => void; preferredIntent: Intent; showStarters: boolean;
  intentRequest?: { id: string; intent: Intent; n: number };
  externalBlocked: boolean; activity: (value: boolean) => void;
  locateMessage: (id: string) => Promise<boolean>;
  busy: boolean; loadEarlier: () => Promise<void>;
  summary?: ChatSummary; startIntent?: Intent;
  displayTitle?: string;
  parent?: { name: string; open: () => void; disabled: boolean };
  seededBookmarks?: Bookmarks | null;
  /** Selected canvas nodes attached once to the next coaching send. */
  canvasSelection?: CanvasSelection | null;
  onCanvasSelectionConsumed: () => void;
  /** Selected artifact passage attached once to the next coaching send. */
  artifactSelection?: ArtifactSelection | null;
  onArtifactSelectionConsumed: () => void;
}) {
  const storageKey = `codesign-mode:${owner}:${page.notebook.id}`;
  const legacyKey = `codesign-lecture:${owner}:${page.notebook.id}`;
  const [savedDraft] = useState(() => restore(storageKey, legacyKey));
  const initial = useRef(savedDraft);
  useEffect(() => {
    try {
      if (sessionStorage.getItem(legacyKey) !== null && savedDraft !== empty) {
        if (sessionStorage.getItem(storageKey) === null) sessionStorage.setItem(storageKey, JSON.stringify(savedDraft));
        sessionStorage.removeItem(legacyKey);
      }
    } catch { /* Tab-storage recovery remains available in memory. */ }
  }, [legacyKey, savedDraft, storageKey]);
  const canvasSelectionRef = useRef<CanvasSelection | null>(canvasSelection ?? null);
  canvasSelectionRef.current = canvasSelection ?? null;
  const artifactSelectionRef = useRef<ArtifactSelection | null>(artifactSelection ?? null);
  artifactSelectionRef.current = artifactSelection ?? null;
  const [mode, setIntent] = useState<Intent | undefined>(initial.current.pending?.intent ?? initial.current.intent ?? (page.total_count ? savedIntent(page, project) : startIntent));
  const [canvasProposal, setCanvasProposal] = useState<{ messageId: string; content: string } | null>(null);
  const intent = mode ?? preferredIntent;
  const reviewKey = `codesign-review:${owner}:${page.notebook.id}`;
  const initialReview = useRef(restoreReview(reviewKey));
  const [pathOpen, setPathOpen] = useState(initialReview.current.open);
  const [pathTab, setPathTab] = useState<{ tab?: ReviewTab; n: number }>({ tab: initialReview.current.tab, n: 0 });
  useEffect(() => {
    try { sessionStorage.setItem(reviewKey, JSON.stringify({ open: pathOpen, tab: pathTab.tab })); }
    catch { /* Review still works in memory when optional tab storage is unavailable. */ }
  }, [reviewKey, pathOpen, pathTab.tab]);
  const [milestone, setMilestone] = useState<Milestone | null>(null);
  const [transition, setTransition] = useState<{ from: string; to: string } | null>(null);
  const allDone = useRef(project.stages.every(stage => stage.completed));
  const checkInKey = `codesign-checkin:${owner}:${page.notebook.id}`;
  const startersKey = `codesign-starters:${owner}:${page.notebook.id}`;
  const [dismissedRules, setDismissedRules] = useState<string[]>(() => {
    try { const value = JSON.parse(sessionStorage.getItem(checkInKey) || '[]'); return Array.isArray(value) ? value.filter(item => typeof item === 'string') : []; }
    catch { return []; }
  });
  const [checkInHidden, setCheckInHidden] = useState(false);
  const [startersCollapsed, setStartersCollapsedState] = useState(() => {
    try { return sessionStorage.getItem(startersKey) === 'collapsed'; } catch { return false; }
  });
  const layout = useWorkspaceLayoutContext();
  // The saved Review width rides a CSSOM rule: the production CSP blocks inline style attributes.
  useEffect(() => { applyLayoutStyle('conversation', { '--review-w': `${layout.reviewWidth}px` }); }, [layout.reviewWidth]);
  const reviewDocked = layout.review === 'docked';
  const { setReviewOpen } = layout;
  // The sidebar gives up room while Review is docked beside the chat.
  useEffect(() => {
    setReviewOpen(pathOpen);
    return () => setReviewOpen(false);
  }, [pathOpen, setReviewOpen]);
  function setStartersCollapsed(value: boolean) {
    setStartersCollapsedState(value);
    try { if (value) sessionStorage.setItem(startersKey, 'collapsed'); else sessionStorage.removeItem(startersKey); } catch { /* Optional tab preference. */ }
  }
  const transcript = useRef<HTMLDivElement>(null);
  const stickToLatest = useRef(true);
  const scrollingToLatest = useRef(false);
  const [atLatest, setAtLatest] = useState(true);
  useEffect(() => {
    const panel = transcript.current;
    if (!panel) return;
    const observer = new ResizeObserver(() => {
      if (stickToLatest.current) panel.scrollTop = panel.scrollHeight;
      setAtLatest(panel.scrollHeight - panel.scrollTop - panel.clientHeight <= 4);
    });
    observer.observe(panel);
    if (panel.firstElementChild) observer.observe(panel.firstElementChild);
    return () => observer.disconnect();
  }, []);
  const pathToggle = useRef<HTMLButtonElement>(null);
  const reviewPanel = useRef<HTMLDialogElement>(null);
  /** An explicit Review-button click earns the modal drawer; a restored-open panel never blocks the page. */
  const explicitReview = useRef(false);
  useLayoutEffect(() => {
    const panel = reviewPanel.current;
    if (!panel) return;
    panel.close();
    if (layout.review === 'docked' || !explicitReview.current) panel.show();
    else panel.showModal();
    panel.querySelector<HTMLElement>('#review-heading')?.focus({ preventScroll: true });
    return () => panel.close();
  }, [pathOpen, layout.review]);
  // A panel restored across visits must say so: the student sees it reopened, not a surprise overlay.
  useEffect(() => {
    if (initialReview.current.open) setReviewStatus('Reopened your saved Review panel from your last visit.');
  }, []);
  const [moving, setMoving] = useState(false);
  const [projectUncertain, setProjectUncertain] = useState(false);
  const intentRef = useRef(intent);
  intentRef.current = intent;
  const [text, setText] = useState(initial.current.text);
  const [attachments, setAttachments] = useState<Attachment[]>(initial.current.attachments ?? []);
  const [uploading, setUploading] = useState(false);
  const attachmentInput = useRef<HTMLInputElement>(null);
  const textRef = useRef(text);
  const [reviewStatus, setReviewStatus] = useState('');
  const [edit, setEdit] = useState<{ id: string; text: string } | null>(null);
  const editField = useRef<HTMLTextAreaElement>(null);
  useLayoutEffect(() => {
    const field = editField.current;
    if (!field) return;
    const measure = document.createElement('canvas').getContext('2d');
    if (measure) {
      const style = getComputedStyle(field);
      measure.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
      const textWidth = field.value.split('\n').reduce((width, line) => Math.max(width, measure.measureText(line).width), 0);
      // Include the textbox padding and message border; CSS caps it to the chat width.
      field.closest<HTMLElement>('.message')?.style.setProperty('--edit-width', `${Math.max(260, Math.ceil(textWidth) + 58)}px`);
    }
    field.style.height = 'auto';
    field.style.height = `${Math.min(Math.max(field.scrollHeight, 52), 360)}px`;
  }, [edit?.id, edit?.text]);
  function cancelEdit(messageId: string) {
    setEdit(null);
    window.requestAnimationFrame(() => document.getElementById(`edit-trigger-${messageId}`)?.focus({ preventScroll: true }));
  }
  const [feedbackBusy, setFeedbackBusy] = useState(false);
  const [bookmarks, setBookmarks] = useState<Bookmarks | null>(null);
  const [bookmarkError, setBookmarkError] = useState('');
  const [highlighted, setHighlighted] = useState('');
  const bookmarkRead = useRef(0);
  const appliedSeed = useRef<Bookmarks | null>(null);
  const currentRevision = useRef(page.conversation_revision);
  currentRevision.current = page.conversation_revision;
  const [storageError, setStorageError] = useState(false);
  const [evidence, setEvidence] = useState<{ citation: Citation; message: string } | null>(null);
  const [downloadError, setDownloadError] = useState('');
  const composer = useRef<HTMLTextAreaElement>(null);
  const lastScaffold = useRef('');
  const evidenceHeading = useRef<HTMLHeadingElement>(null);
  const citationButton = useRef<HTMLButtonElement | null>(null);
  const returnScroll = useRef(0);
   const path = `/api/v1/reader/threads/${encodeURIComponent(page.notebook.id)}`;
  const queryClient = useQueryClient();
  // One lifecycle owns the coach turn: request/owner identity, phases and recovery.
  const {
    active, controller, lock, verify,
    watching, canStop, checking, stopping,
    pending, setPending, pendingRef,
    status, setStatus, preview,
    send, reconcile, stopGeneration,
  } = useChatLifecycle({
    threadId: page.notebook.id, owner, expired, refresh, composer,
    busy, moving, externalBlocked, feedbackBusy, projectUncertain,
    stickToLatest,
    draft: { text: textRef, intent: intentRef, attachments, remember },
    initialPending: initial.current.pending,
    canvasSelection: { current: canvasSelectionRef.current, clear: onCanvasSelectionConsumed },
    artifactSelection: { current: artifactSelectionRef.current, clear: onArtifactSelectionConsumed },
  });
  textRef.current = text;
  useLayoutEffect(() => {
    const field = composer.current;
    if (!field) return;
    field.style.height = 'auto';
    field.style.height = `${Math.min(Math.max(field.scrollHeight, 60), 200)}px`;
    if (stickToLatest.current && transcript.current) transcript.current.scrollTop = transcript.current.scrollHeight;
  }, [text]);

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

  async function stageAction(route: string, body: object) {
    if (lock.current || pendingRef.current || busy || moving || externalBlocked || feedbackBusy) return;
    // Only a confirmed move can become a milestone, and only if the refreshed project really changed stage.
    const resolving = project.pending && route.startsWith('resolve/') && (body as { accepted?: boolean }).accepted === true
      ? { from: project.current_stage, to: project.pending.to_stage } : null;
    lock.current = true;
    setMoving(true);
    setProjectUncertain(true);
    setReviewStatus('Checking saved project…');
    try {
      await verify();
      // Generated decision writes; the confirmed projection reconciles the
      // owner-fenced resource while the authoritative refresh updates the view.
      if (route === 'select-stage') {
        const confirmed = await selectStage(page.notebook.id, (body as { stage_id: string }).stage_id, controller.current.signal);
        void reconcileProject(queryClient, owner, page.notebook.id, () => confirmed);
      } else if (route.startsWith('resolve/')) {
        const confirmed = await resolveTransition(page.notebook.id, route.slice('resolve/'.length),
          (body as { accepted: boolean }).accepted, controller.current.signal);
        void reconcileProject(queryClient, owner, page.notebook.id, () => confirmed);
      }
      await verify();
      // Even an ambiguous POST is reconciled by reads; decisions are never automatically replayed.
      await refresh();
      if (active.current) {
        setProjectUncertain(false);
        if (resolving) setTransition(resolving);
        setReviewStatus('Saved project updated.');
      }
    } catch (error) {
      if (error instanceof ApiError && [401, 403].includes(error.status)) { expired(); return; }
      if (error instanceof ApiError) {
        if (active.current) {
          setReviewStatus('That action is no longer available. Saved project refreshed.');
          try { await refresh(); } catch { /* The refresh failure is already reported. */ }
        }
        return;
      }
      if (active.current) setReviewStatus('Could not verify the project action. Refresh saved project before continuing.');
    } finally { if (active.current) setMoving(false); lock.current = false; }
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

  /** Bring an exact bookmarked original into the transcript and hand keyboard focus to it. */
  async function jumpToMessage(id: string) {
    if (lock.current || busy || externalBlocked) return;
    lock.current = true; setFeedbackBusy(true); stickToLatest.current = false;
    try {
      if (!await locateMessage(id)) throw new Error('Original unavailable');
      if (!active.current) return;
      setPathOpen(false); setHighlighted(id); setStatus('Original message highlighted.');
    } catch { if (active.current) setStatus('Could not open the original message. Refresh this chat and try again.'); }
    finally { lock.current = false; if (active.current) setFeedbackBusy(false); }
  }
  useEffect(() => {
    if (!highlighted || pathOpen) return;
    const frame = window.requestAnimationFrame(() => {
      const target = document.getElementById(`message-${highlighted}`);
      target?.scrollIntoView({ block: 'start', behavior: 'instant' });
      target?.focus({ preventScroll: true });
    });
    const timer = window.setTimeout(() => setHighlighted(''), 6000);
    return () => { window.cancelAnimationFrame(frame); window.clearTimeout(timer); };
  }, [highlighted, page.messages, pathOpen]);

  /** Read all saved stars and fence late responses to this owner and active revision. */
  async function readBookmarks() {
    const read = ++bookmarkRead.current;
    const savedValue = await fetchConfirmedBookmarks(owner, page.notebook.id, controller.current.signal);
    await verify();
    if (savedValue.conversation_revision !== currentRevision.current) {
      throw new Error('History changed. Reopen this chat.');
    }
    if (read === bookmarkRead.current) {
      setBookmarks(savedValue); setBookmarkError('');
      // The confirmed projection reconciles the owner-fenced resource.
      void reconcileBookmarks(queryClient, owner, page.notebook.id, () => savedValue);
    }
    return savedValue;
  }
  useEffect(() => {
    // The verified workspace open read already carries this thread's bookmarks
    // at the current revision; only a mismatch needs its own read. The applied
    // seed never clobbers newer local reconciliation (for example an explicit
    // star re-read within the same revision).
    const seed = seededBookmarks && seededBookmarks.thread_id === page.notebook.id
      && seededBookmarks.conversation_revision === page.conversation_revision ? seededBookmarks : null;
    if (seed) {
      if (appliedSeed.current === seed) return;
      appliedSeed.current = seed;
      setBookmarks(seed); setBookmarkError('');
      return;
    }
    appliedSeed.current = null;
    let cancelled = false;
    void readBookmarks().catch(() => {
      if (!cancelled && active.current) setBookmarkError('Could not load bookmarks. Refresh bookmarks to try again.');
    });
    return () => { cancelled = true; };
  }, [page, seededBookmarks]);
  const visibleBookmarks = bookmarks?.conversation_revision === page.conversation_revision ? bookmarks : null;
  const isStarred = (id: string, fallback: boolean) => visibleBookmarks ? visibleBookmarks.messages.some(item => item.id === id) : fallback;

  /** Save an explicit state, then reconcile by reading rather than replaying a lost write. */
  async function star(message: string, starred: boolean) {
    if (lock.current || feedbackBusy || externalBlocked) return;
    lock.current = true; setFeedbackBusy(true);
    try {
      await verify();
      try {
        // A generated contract write; a lost response can still have saved the
        // state, so the read below decides rather than replaying the write.
        await setStar(page.notebook.id, message, starred, controller.current.signal);
      } catch (error) {
        if (error instanceof ApiError && [401, 403].includes(error.status)) { expired(); return; }
        /* A lost response can still have saved the state. Read before reporting success. */
      }
      const saved = await readBookmarks();
      const actual = saved.messages.some(item => item.id === message);
      const notice = actual === starred ? (starred ? 'Message starred.' : 'Star removed.') : 'Star was not saved. Try again.';
      setStatus(notice);
      if (actual !== starred) setBookmarkError(notice);
    } catch { if (active.current) {
      const notice = 'Could not verify the star. Check your connection and refresh bookmarks before trying again.';
      setStatus(notice); setBookmarkError(notice);
    } }
    finally { lock.current = false; if (active.current) setFeedbackBusy(false); }
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
  // Neither a pending receipt nor an in-flight turn may lock the whole workspace:
  // the receipt is persisted before the request leaves, so navigating away is
  // recoverable (reopening the chat auto-reconciles). Only local UI work that a
  // remount would lose (stage moves, uploads, project checks, feedback) locks.
  useEffect(() => { activity(moving || uploading || projectUncertain || feedbackBusy); }, [moving, uploading, projectUncertain, feedbackBusy]);
  const editIndex = pending?.message ? page.messages.findIndex(message => message.id === pending.message) : -1;
  const visibleMessages = editIndex >= 0 ? page.messages.slice(0, editIndex) : page.messages;

  useEffect(() => { if (evidence) evidenceHeading.current?.focus({ preventScroll: true }); }, [evidence]);

  useEffect(() => {
    if (stickToLatest.current && transcript.current) transcript.current.scrollTop = transcript.current.scrollHeight;
  }, [page.messages, preview, watching, project.pending?.id, milestone]);
  useEffect(() => {
    const complete = project.stages.every(stage => stage.completed);
    if (complete && !allDone.current) setMilestone({ kind: 'finished' });
    allDone.current = complete;
  }, [project]);
  useEffect(() => {
    if (!transition) return;
    setTransition(null);
    if (transition.from === transition.to || project.current_stage !== transition.to) return;
    if (project.stages.every(stage => stage.completed)) { setMilestone({ kind: 'finished' }); return; }
    const completed = project.stages.findIndex(stage => stage.id === transition.from) + 1;
    const next = project.stages.find(stage => stage.id === transition.to)?.label;
    const from = project.stages.find(stage => stage.id === transition.from)?.label ?? '';
    if (completed > 0 && next) setMilestone({ kind: 'stage', completed, total: project.stages.length, next, from });
  }, [transition, project]);

  function closePath() {
    explicitReview.current = false;
    setPathOpen(false);
    window.requestAnimationFrame(() => pathToggle.current?.focus({ preventScroll: true }));
  }

  const isEmpty = page.messages.length === 0 && !watching && !pending;
  const reviewDisabled = watching || checking || busy || moving || uploading || !!pending || projectUncertain || externalBlocked || feedbackBusy;
  /** Single path for every scaffold button: keep the draft, optionally switch mode, focus the composer. No send. */
  function insertScaffold(prompt: string, switchTo?: Intent) {
    if (switchTo && !(watching || checking || moving || pendingRef.current)) { intentRef.current = switchTo; setIntent(switchTo); }
    // Replace an empty draft or an untouched earlier scaffold. Never delete words the student typed: add below them.
    const current = textRef.current;
    const next = !current.trim() || current === lastScaffold.current ? prompt : `${current}\n\n${prompt}`;
    lastScaffold.current = next;
    remember(next, pendingRef.current);
    if (pathOpen && !reviewDocked) {
      setReviewStatus('Prompt added to your draft. Close Review to edit it.');
      return;
    }
    window.requestAnimationFrame(() => {
      const field = composer.current;
      if (!field) return;
      field.focus({ preventScroll: true });
      field.setSelectionRange(next.length, next.length);
      field.scrollTop = field.scrollHeight;
    });
  }
  const choosePrompt = (prompt: string) => insertScaffold(prompt);
  const stageLabel = project.stages.find(stage => stage.id === project.current_stage)?.label ?? '';
  const projectMode = intent === 'project';
  const projectWork = projectMode && hasProjectWork(project);
  const pendingDecision = projectMode && project.pending;
  const stageNumber = Math.max(0, project.stages.findIndex(stage => stage.id === project.current_stage)) + 1;
  const turnBusy = watching || checking || moving || uploading || !!pending;
  const checkIn = projectMode && !checkInHidden && !milestone && !isEmpty && !turnBusy && !text.trim() && !projectUncertain && !(pathOpen && !reviewDocked)
    ? chooseCheckIn(project, summary, intent, dismissedRules) : null;
  function dismissCheckIn(item: CheckIn) {
    const next = [...dismissedRules, item.rule];
    setCheckInHidden(true);
    setDismissedRules(next);
    try { sessionStorage.setItem(checkInKey, JSON.stringify(next)); } catch { /* Optional tab preference. */ }
  }
  const showChips = projectMode && showStarters && !isEmpty && !checkIn && !milestone && !text.trim() && !turnBusy;
  // The composer dock changes height when a check-in or the suggestions appear. Keep the latest message in view.
  useEffect(() => {
    if (stickToLatest.current && transcript.current) transcript.current.scrollTop = transcript.current.scrollHeight;
  }, [checkIn?.rule, showChips, startersCollapsed]);
  const openReview = (tab?: ReviewTab) => { explicitReview.current = true; setPathTab(value => ({ tab: tab ?? value.tab, n: value.n + 1 })); setPathOpen(true); };
  async function decideInline(route: string, body: object) {
    await stageAction(route, body);
    window.requestAnimationFrame(() => composer.current?.focus({ preventScroll: true }));
  }

  function startDesignChat() {
    setPathOpen(false);
    if (!pendingRef.current) {
      intentRef.current = 'project';
      setIntent('project');
      remember(textRef.current, null);
    }
    window.requestAnimationFrame(() => composer.current?.focus({ preventScroll: true }));
  }

  // Home asked this already-open empty chat to start in a given mode. Each request applies once.
  const appliedIntent = useRef(intentRequest?.n ?? 0);
  useEffect(() => {
    if (!intentRequest || intentRequest.n === appliedIntent.current) return;
    appliedIntent.current = intentRequest.n;
    if (intentRequest.id !== page.notebook.id || pendingRef.current || turnBusy) return;
    intentRef.current = intentRequest.intent;
    setIntent(intentRequest.intent);
    remember(textRef.current, null);
  }, [intentRequest?.n]);

  return <section aria-label="Saved conversation" className={`conversation ${pathOpen ? 'review-open' : ''}`}
    data-review={pathOpen ? layout.review : undefined}>
    <header className="chat-heading">
      <h2 title={parent ? `${parent.name} › ${displayTitle}` : displayTitle}>
        {parent ? <><button className="crumb-parent" disabled={parent.disabled} aria-label={`Open notebook ${parent.name}`} onClick={parent.open}>
          <Icon name="folder"/><span>{parent.name}</span></button><span className="crumb-sep" aria-hidden="true">›</span></> : null}
        <span className="crumb-title">{displayTitle}</span>
      </h2>
      <button ref={pathToggle} className="path-toggle" aria-haspopup="dialog" aria-expanded={pathOpen}
        aria-description={pendingDecision ? 'Stage decision pending' : undefined}
        aria-controls={pathOpen ? 'project-review' : undefined}
        onClick={() => pathOpen ? closePath() : openReview(pendingDecision ? 'Progression' : undefined)}>
        <Icon name="path"/> Review
        {projectWork ? <span className="path-progress"><span aria-hidden="true"> · </span>
          <span className="path-count">{stageNumber}/{project.stages.length}<span className="sr-only"> stages, current: {stageLabel}</span></span>
          <span className="path-stage" aria-hidden="true"> · {stageLabel}</span></span> : null}
        {pendingDecision ? <span className="decision-dot" aria-hidden="true"/> : null}
      </button>
    </header>
    <div className="conversation-chat">
    <div id="chat-transcript" className={`transcript ${isEmpty ? 'transcript-empty' : ''}`} ref={transcript} onScroll={event => {
      const panel = event.currentTarget;
      const latest = panel.scrollHeight - panel.scrollTop - panel.clientHeight <= 4;
      stickToLatest.current = latest;
      setAtLatest(latest);
    }} onWheel={() => { scrollingToLatest.current = false; }} onPointerDown={() => { scrollingToLatest.current = false; }} onKeyDown={() => { scrollingToLatest.current = false; }} onScrollEnd={event => {
      if (!scrollingToLatest.current) return;
      const panel = event.currentTarget;
      if (panel.scrollHeight - panel.scrollTop - panel.clientHeight > 4) {
        // New output may move the destination during the first smooth scroll.
        panel.scrollTo({ top: panel.scrollHeight, behavior: 'smooth' });
      } else { scrollingToLatest.current = false; stickToLatest.current = true; }
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
      <h1>{intent === 'improve' ? 'Improve my design' : 'Make room for a better question.'}</h1>
      <p>{intent === 'improve' ? 'Share your design and what you’d like to improve.' : 'Bring a half-formed thought. We’ll work through it together.'}</p>
      {showStarters && intent === 'project' ? <ReasoningPrompts disabled={checking || moving || externalBlocked} onChoose={choosePrompt}/> : null}
    </div> : null}
    {visibleMessages.map(message => <article id={`message-${message.id}`} data-message-id={message.id} data-highlighted={highlighted === message.id || undefined} tabIndex={-1} className={`message ${message.role === 'user' ? 'student' : 'coach'}${edit?.id === message.id ? ' editing' : ''}`} key={message.id}>
      <h3>{message.role === 'user' ? 'You' : 'Coach'}</h3>
      {edit?.id === message.id ? <form className="message-edit" aria-label="Edit your message" onKeyDown={event => {
        if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); cancelEdit(message.id); }
      }} onSubmit={event => {
        event.preventDefault(); const receipt = { key: newRequestKey(), text: edit.text, message: edit.id }; setEdit(null); void send(false, receipt);
      }}>
        <label className="sr-only" htmlFor={`edit-${message.id}`}>Revise your message</label>
        <div className="message-edit-box">
          <textarea ref={editField} autoFocus rows={1} id={`edit-${message.id}`} aria-describedby={`edit-note-${message.id}`} value={edit.text} maxLength={12000} onChange={event => setEdit({ ...edit, text: event.target.value })}/>
          <div className="message-edit-actions">
            <button type="button" aria-label="Cancel edit" title="Cancel edit" onClick={() => cancelEdit(message.id)}><Icon name="close"/></button>
            <button className="edit-submit" aria-label="Confirm edit & ask again" title="Confirm edit & ask again" disabled={!edit.text.trim() || watching || checking || busy || moving || feedbackBusy || !!pending || externalBlocked || projectUncertain}><Icon name="arrow"/></button>
          </div>
        </div>
        <p className="supporting" id={`edit-note-${message.id}`}>Sending replaces this message and later replies, including any Thinking Path progress from those replies. Your composer draft is kept.</p>
      </form> : <>
      {message.role === 'user' ? <div className="message-content">{message.content}</div> : <CoachText text={message.content}/>}
      <div className="message-actions">
        <button aria-label={isStarred(message.id, message.starred) ? 'Unstar message' : 'Star message'}
          title={isStarred(message.id, message.starred) ? 'Unstar message' : 'Star message'}
          aria-pressed={isStarred(message.id, message.starred)} className="message-star"
          disabled={feedbackBusy || watching || checking || moving || !!pending || externalBlocked}
          onClick={() => void star(message.id, !isStarred(message.id, message.starred))}><Icon name="star"/></button>
        <button aria-label={message.role === 'user' ? 'Copy your message' : 'Copy answer'} title="Copy" onClick={() => { void navigator.clipboard.writeText(message.content).then(() => setStatus('Message copied.')).catch(() => setStatus('Could not copy. Select the message text to copy it.')); }}><Icon name="copy"/></button>
        <button aria-label="Add to canvas" title="Add to a design canvas" disabled={watching || checking || moving || !!pending || externalBlocked}
          onClick={() => setCanvasProposal({ messageId: message.id, content: message.content })}><Icon name="plus"/></button>
        {message.role === 'user' ? <button aria-label="Edit message" title="Edit message" disabled={watching || checking || moving || !!pending || externalBlocked || projectUncertain} id={`edit-trigger-${message.id}`} onClick={() => { stickToLatest.current = false; setEdit({ id: message.id, text: message.content }); }}><Icon name="edit"/></button> : null}
        {message.role !== 'user' ? <button className="use-in-project" disabled={watching || checking || moving || !!pending || externalBlocked}
          onClick={() => insertScaffold(feedbackToProjectScaffold(message.content), 'project')}><Icon name="path"/> Use in my project</button> : null}
        {message.feedback_available ? <div role="group" aria-label="Was this answer useful?">
          {(['useful', 'not_useful'] as const).map(kind => <button key={kind} aria-label={kind === 'useful' ? 'Useful' : 'Not useful'} title={kind === 'useful' ? 'Useful' : 'Not useful'} aria-pressed={message.rating === kind} disabled={feedbackBusy || watching || checking || !!pending || externalBlocked} onClick={() => void rate(message.id, kind)}><Icon name={kind === 'useful' ? 'up' : 'down'}/></button>)}
        </div> : null}
      </div>
      </>}
      {message.citations.length ? <div className="citations" aria-label="Supporting evidence">{message.citations.map(citation =>
        <button key={`${citation.label}:${citation.source_id}`} onClick={event => {
          returnScroll.current = transcript.current?.scrollTop || 0; citationButton.current = event.currentTarget;
          setDownloadError(''); setEvidence({ citation, message: message.id });
        }}>{citationText(citation)}</button>)}</div> : null}
      {message.role !== 'user' && message.canvas_suggestions?.length
        ? <CanvasSuggestions threadId={page.notebook.id} owner={owner}
            suggestions={message.canvas_suggestions}
            disabled={watching || checking || moving || !!pending || externalBlocked || projectUncertain}/>
        : null}
      {message.role !== 'user' && message.artifact_feedback?.length
        ? message.artifact_feedback.map(feedback => <ArtifactFeedbackCard key={feedback.id}
            threadId={page.notebook.id} owner={owner} feedback={feedback}
            disabled={watching || checking || moving || !!pending || externalBlocked || projectUncertain}/>)
        : null}
      {message.role !== 'user' && message.canvas_draft
        ? <CanvasDraftCard threadId={page.notebook.id} owner={owner} draft={message.canvas_draft}
            disabled={watching || checking || moving || !!pending || externalBlocked || projectUncertain}/>
        : null}
    </article>)}
    {projectMode && milestone ? <MilestoneBanner milestone={milestone} onDismiss={() => setMilestone(null)} onReview={() => { setMilestone(null); openReview('Summary'); }}
      onReflect={from => { setMilestone(null); insertScaffold(reflectionScaffold(from), 'project'); }}/> : null}
    {projectMode ? <StageRecommendation project={project} disabled={reviewDisabled} act={decideInline}/> : null}
    {evidence ? <aside className="evidence" aria-label="Cited evidence">
      <div className="evidence-heading"><h3 ref={evidenceHeading} tabIndex={-1}>{citationText(evidence.citation)}</h3>
        <button onClick={() => {
          setEvidence(null); citationButton.current?.focus({ preventScroll: true }); transcript.current?.scrollTo(0, returnScroll.current);
        }}>Return to answer</button></div>
      <p className="supporting">Excerpt saved with this answer</p>
      <blockquote>{evidence.citation.excerpt || 'No excerpt was saved. Download the original to inspect it.'}</blockquote>
      <button onClick={() => void download()}>Download original source</button>
      {downloadError ? <p role="alert">{downloadError}</p> : null}
    </aside> : null}
    {preview ? <article className="message preview"><h3>Coach · unsaved preview</h3><CoachText text={preview}/></article> : null}
    {pending && !watching ? <div className="recovery-actions" role="status" aria-label="Checking your answer">
      {checking ? <span className="typing-dots" aria-hidden="true"><i/><i/><i/></span> : <>
        <span>{status}</span>
        <button type="button" disabled={externalBlocked || busy} onClick={() => void reconcile(pending)}>Check saved answer</button>
      </>}
    </div> : null}
    </div></div>
    <div className="composer-dock"><div className="chat-column">

    {!isEmpty && (watching || checking || !atLatest) ? <div className="latest-control-row">
      <button type="button" className="latest-control" aria-controls="chat-transcript"
        aria-label={watching || checking ? 'Jump to latest message, coach is working' : 'Jump to latest message'}
        aria-busy={watching || checking} title={watching || checking ? 'Coach is working · Jump to latest message' : 'Jump to latest message'}
        onClick={() => {
          const panel = transcript.current;
          if (!panel) return;
          const animate = !window.matchMedia('(prefers-reduced-motion: reduce)').matches
            && panel.scrollHeight - panel.scrollTop - panel.clientHeight > 4;
          scrollingToLatest.current = animate;
          stickToLatest.current = !animate;
          panel.scrollTo({ top: panel.scrollHeight, behavior: animate ? 'smooth' : 'instant' });
        }}>
        {watching || checking ? <span className="typing-dots" aria-hidden="true"><i/><i/><i/></span> : <Icon name="arrowDown"/>}
      </button>
    </div> : null}
    {checkIn ? <CoachCheckIn checkIn={checkIn} onAct={item => insertScaffold(item.scaffold, 'project')} onDismiss={dismissCheckIn}/> : null}
    {showChips ? <StageStarters stageId={project.current_stage} disabled={externalBlocked} collapsed={startersCollapsed} setCollapsed={setStartersCollapsed} onChoose={choosePrompt}/> : null}
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
      {canvasSelection ? <p className="canvas-selection-chip" role="status">
        <Icon name="path"/> Discussing canvas node: {canvasSelection.label}
        <button type="button" className="icon-button" aria-label="Stop discussing the canvas node"
          onClick={onCanvasSelectionConsumed}><Icon name="close"/></button>
      </p> : null}
      {artifactSelection ? <p className="canvas-selection-chip" role="status">
        <Icon name="edit"/> Discussing draft: {artifactSelection.label}
        <button type="button" className="icon-button" aria-label="Stop discussing the draft"
          onClick={onArtifactSelectionConsumed}><Icon name="close"/></button>
      </p> : null}
      <label className="sr-only" htmlFor="lecture-question">{intent === 'improve' ? 'What you want to improve' : 'Your project contribution'}</label>
      <textarea ref={composer} id="lecture-question" value={text} maxLength={12000} rows={3} aria-describedby="composer-hint" onKeyDown={event => {
        if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
          event.preventDefault();
          event.currentTarget.form?.requestSubmit();
        }
      }}
        placeholder={intent === 'improve' ? "Share your design and what you’d like to improve…" : "Share an idea or ask a question…"} onChange={event => remember(event.target.value, pendingRef.current)}/>
      <div className="composer-actions">
        <button className="icon-button attach-button" type="button" aria-label="Attach files" title="Attach files" disabled={externalBlocked || uploading || watching || !!pending} onClick={() => attachmentInput.current?.click()}><Icon name="attach"/></button>
        <ModeSwitch value={intent} disabled={watching || checking || moving || !!pending} onChange={next => {
        intentRef.current = next; setIntent(next); remember(textRef.current, pendingRef.current);
      }}/>
        <span className="composer-hint" id="composer-hint">↵ send · ⇧ ↵ new line</span>
        {intent === 'project' ? <button className="hint-button" type="button" title="Ask the coach for a question that helps you think, not the answer" disabled={externalBlocked || watching || checking || moving || !!pending}
          onClick={() => insertScaffold(hintScaffold(stageLabel), 'project')}>
          <Icon name="spark"/><span>Hint</span></button> : null}
        {watching ? <button className="primary send-button" type="button" aria-label="Stop generating"
          title={stopping ? 'Stopping…' : 'Stop generating'} disabled={!canStop || stopping}
          onClick={() => void stopGeneration()}><Icon name="close"/></button> :
        <button className="primary send-button" aria-label="Send message" title="Send message" type="submit" disabled={watching || checking || busy || moving || projectUncertain || externalBlocked || uploading || feedbackBusy || !!pending || !text.trim()}><Icon name="arrow"/></button>}</div>
    </form>
    {storageError ? <p role="alert">Tab storage is unavailable. Keep a copy of your draft before reloading.</p> : null}
    {/* In-progress is wordless: the transcript's bouncing dots carry the state. */}
    <div className="turn-status" role="status" aria-live="polite">{watching || checking || pending ? '' : status}</div>
    <p className="composer-note">Your coach can make mistakes. You decide what goes into your work.</p>
    </div></div>
    </div>
    {pathOpen ? <dialog ref={reviewPanel} id="project-review" className="project-panel" aria-labelledby="review-heading"
      onCancel={event => { event.preventDefault(); closePath(); }}
      onClick={event => {
        // A click on the dimmed page behind a drawer dismisses it.
        if (reviewDocked || event.target !== event.currentTarget) return;
        const box = event.currentTarget.getBoundingClientRect();
        if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) closePath();
      }}
      onKeyDown={event => {
        if (event.key === 'Escape') {
          event.preventDefault();
          closePath();
        }
      }}>
      <ThinkingPath projectMode={projectMode} bookmarks={visibleBookmarks?.messages ?? []} bookmarkError={bookmarkError} bookmarksReady={!!visibleBookmarks}
        refreshBookmarks={() => { void readBookmarks().catch(() => setBookmarkError('Could not load bookmarks. Try again.')); }}
        jumpToMessage={id => void jumpToMessage(id)} removeStar={id => void star(id, false)} key={pathTab.n} project={project} title={displayTitle} initialTab={pathTab.tab} onTabChange={tab => setPathTab(value => ({ ...value, tab }))} insertScaffold={insertScaffold}
        disabled={reviewDisabled}
        act={stageAction} startInChat={startDesignChat} onClose={closePath} status={reviewStatus}>
        {projectUncertain && !moving ? <p className="review-recovery" role="alert">Check saved project before another action. <button disabled={busy} onClick={() => void refreshProject()}>Refresh saved project</button></p> : null}
      </ThinkingPath>
    </dialog> : null}
    {pathOpen && reviewDocked ? <ResizeHandle side="review" label="Resize Review panel" value={layout.reviewWidth} min={REVIEW_LIMITS.min} max={layout.reviewMax}
      onResize={layout.resizeReview} onReset={layout.resetReview}/> : null}
    {canvasProposal ? <ChatToCanvasProposal
      threadId={page.notebook.parent_notebook_id ?? page.notebook.id}
      messageId={canvasProposal.messageId} content={canvasProposal.content}
      onClose={() => setCanvasProposal(null)}
      onCreated={() => { setCanvasProposal(null); setStatus('Node added to your canvas.'); }}/> : null}
  </section>;
}
