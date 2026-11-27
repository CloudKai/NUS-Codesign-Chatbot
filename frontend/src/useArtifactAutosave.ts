/** Debounced confirmed autosave for one owned revision-guarded subject; conflicting drafts are never silently overwritten. */
import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from './api';

export type AutosaveState = 'editing' | 'saving' | 'saved' | 'offline' | 'failure' | 'conflict';

/** The minimal saved subject the autosave reconciles: an artifact or a canvas. */
export interface AutosaveSubject {
  id: string;
  owner_id: string;
  revision: number;
  title: string;
}

interface SaveSnapshot {
  document: unknown;
  title: string;
}

interface SaveAttempt extends SaveSnapshot {
  baseRevision: number;
}

export interface AutosaveDraft extends SaveSnapshot {
  savedAt: string;
  /** Older drafts have no recorded base and require explicit resolution. */
  baseRevision?: number;
  /** A write may have committed even if this tab never saw its acknowledgement. */
  attempt?: SaveAttempt;
}

export type AutosaveKind = 'artifact' | 'canvas';

export const AUTOSAVE_DEBOUNCE_MS = 2_000;

/** Owner-scoped unsaved-draft storage; late responses never cross owners or subjects. */
export function draftKey(owner: string, subjectId: string, kind: AutosaveKind = 'artifact'): string {
  return `codesign-${kind}-draft:${owner}:${subjectId}`;
}

export function readDraft(owner: string, subjectId: string, kind: AutosaveKind = 'artifact'): AutosaveDraft | null {
  try {
    const raw = sessionStorage.getItem(draftKey(owner, subjectId, kind));
    const draft = raw ? JSON.parse(raw) as AutosaveDraft : null;
    return draft && typeof draft.title === 'string' && draft.document ? draft : null;
  } catch { return null; }
}

function writeDraft(owner: string, subjectId: string, draft: AutosaveDraft, kind: AutosaveKind): void {
  try { sessionStorage.setItem(draftKey(owner, subjectId, kind), JSON.stringify(draft)); }
  catch { /* Draft persistence is optional; the editor keeps its in-memory copy. */ }
}

function clearDraft(owner: string, subjectId: string, kind: AutosaveKind): void {
  try { sessionStorage.removeItem(draftKey(owner, subjectId, kind)); }
  catch { /* Nothing to clear. */ }
}

/** Compare JSON representations without depending on object key order. */
function snapshotJson(value: unknown): string | undefined {
  return JSON.stringify(value, (_key, entry: unknown) => {
    if (!entry || typeof entry !== 'object' || Array.isArray(entry)) return entry;
    return Object.fromEntries(Object.entries(entry).sort(([key], [other]) => key.localeCompare(other)));
  });
}

/** Drive one debounced, deduplicated, revision-guarded save cycle for the current editor content. */
export function useArtifactAutosave<T extends AutosaveSubject>({ owner, artifact, document, title,
  onSave, readSaved, getSavedDocument, onDiscard, onExpired, enabled, draftKind = 'artifact', onConfirmed,
  debounceMs = AUTOSAVE_DEBOUNCE_MS }: {
  owner: string; artifact: T | null; document: () => unknown; title: () => string;
  onSave: (document: unknown, title: string, revision: number) => Promise<T>;
  readSaved: () => Promise<T>;
  getSavedDocument: (saved: T) => unknown;
  onDiscard?: (saved: T) => void;
  onExpired: () => void; enabled: boolean; draftKind?: AutosaveKind;
  /** Reconcile the confirmed subject (id + revision) into the caller's state after a successful save. */
  onConfirmed?: (subject: T) => void; debounceMs?: number;
}): {
  state: AutosaveState; restoreDraft: (saved: T, draft: AutosaveDraft) => void;
  resolveByReload: () => Promise<void>; resolveByKeep: () => Promise<void>;
  saveNow: () => void; markDirty: () => void;
  applyExternalWrite: (write: (saved: T) => Promise<T>, apply: (confirmed: T) => void) => Promise<boolean>;
} {
  const [state, setState] = useState<AutosaveState>('editing');
  const conflicted = useRef(false);
  const timer = useRef<number | null>(null);
  const inflight = useRef(false);
  const dirty = useRef(false);
  const attempt = useRef<SaveAttempt | null>(null);
  const mounted = useRef(false);
  const head = useRef<T | null>(null);
  const runRef = useRef<() => Promise<void>>(async () => undefined);
  const confirmedRef = useRef(onConfirmed);
  confirmedRef.current = onConfirmed;
  const latest = useRef({ artifact, owner });
  latest.current = { artifact, owner };

  function currentHead(): T | null {
    const current = latest.current.artifact;
    return head.current && current?.id === head.current.id && current.owner_id === head.current.owner_id
      && head.current.revision >= current.revision ? head.current : current;
  }

  function isCurrent(saved: T): boolean {
    return mounted.current && latest.current.owner === saved.owner_id
      && latest.current.artifact?.id === saved.id;
  }

  const clearTimer = useCallback(() => {
    if (timer.current !== null) { window.clearTimeout(timer.current); timer.current = null; }
  }, []);

  const schedule = useCallback((delay: number) => {
    clearTimer();
    timer.current = window.setTimeout(() => { timer.current = null; void runRef.current(); }, delay);
  }, [clearTimer]);

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; clearTimer(); };
  }, [clearTimer]);

  function preserveDraft(saved: T, baseRevision = saved.revision) {
    writeDraft(saved.owner_id, saved.id, {
      document: document(), title: title(), savedAt: new Date().toISOString(), baseRevision,
      ...(attempt.current ? { attempt: attempt.current } : {}),
    }, draftKind);
  }

  function requireResolution() {
    clearTimer();
    conflicted.current = true;
    setState('conflict');
  }

  function matchesAttempt(saved: T, sent: SaveAttempt): boolean {
    return saved.revision === sent.baseRevision + 1 && saved.title === sent.title
      && snapshotJson(getSavedDocument(saved)) === snapshotJson(sent.document);
  }

  function confirmSave(confirmed: T) {
    const trailing = readDraft(confirmed.owner_id, confirmed.id, draftKind);
    attempt.current = null;
    head.current = confirmed;
    confirmedRef.current?.(confirmed);
    if (dirty.current) {
      if (trailing) {
        writeDraft(confirmed.owner_id, confirmed.id, {
          document: trailing.document, title: trailing.title,
          savedAt: trailing.savedAt, baseRevision: confirmed.revision,
        }, draftKind);
      }
      setState('editing');
      schedule(0);
    } else {
      clearTimer();
      setState('saved');
      clearDraft(confirmed.owner_id, confirmed.id, draftKind);
    }
  }

  runRef.current = async (): Promise<void> => {
    const saved = currentHead();
    if (!saved || !isCurrent(saved) || !enabled || inflight.current || conflicted.current) return;
    inflight.current = true;
    setState('saving');
    try {
      if (attempt.current) {
        const previous = attempt.current;
        const current = await readSaved();
        if (!isCurrent(saved)) return;
        if (current.id !== saved.id || current.owner_id !== saved.owner_id) { onExpired(); return; }
        if (matchesAttempt(current, previous)) { confirmSave(current); return; }
        if (current.revision !== previous.baseRevision) { requireResolution(); return; }
      }
      const current = {
        document: document(),
        title: (title() || saved.title).trim().replace(/\s+/g, ' '),
        baseRevision: saved.revision,
      };
      attempt.current = current;
      dirty.current = false; // Pre-flight edits are included in this snapshot.
      preserveDraft(saved);
      const confirmed = await onSave(current.document, current.title, current.baseRevision);
      if (!isCurrent(saved)) return;
      if (confirmed.id !== saved.id || confirmed.owner_id !== saved.owner_id) { onExpired(); return; }
      // A later writer can win between our commit and the server's response read.
      if (confirmed.revision !== current.baseRevision + 1) { requireResolution(); return; }
      confirmSave(confirmed);
    } catch (error) {
      if (!isCurrent(saved)) return;
      if (error instanceof ApiError && [401, 403].includes(error.status)) { onExpired(); return; }
      if (error instanceof ApiError && error.status === 409) {
        requireResolution();
        return;
      }
      setState(error instanceof ApiError ? 'failure' : 'offline');
      clearTimer();
    } finally {
      inflight.current = false;
    }
  };

  /** Mark the editor content dirty, checkpoint the owner-scoped draft and schedule one debounced save. */
  function markDirty() {
    if (!enabled) return;
    dirty.current = true;
    const saved = currentHead();
    if (saved && isCurrent(saved)) {
      if (conflicted.current) {
        const draft = readDraft(saved.owner_id, saved.id, draftKind);
        if (draft) writeDraft(saved.owner_id, saved.id, { ...draft, document: document(), title: title() }, draftKind);
        return;
      }
      preserveDraft(saved);
    }
    if (!inflight.current) setState('editing');
    schedule(debounceMs);
  }

  function saveNow() {
    if (!enabled || inflight.current) return;
    clearTimer();
    void runRef.current();
  }

  /** Resume a compatible draft, or require the student to resolve an unknown or stale base. */
  function restoreDraft(saved: T, draft: AutosaveDraft) {
    if (latest.current.owner !== saved.owner_id) return;
    if (draft.attempt && matchesAttempt(saved, draft.attempt)) {
      dirty.current = draft.title.trim().replace(/\s+/g, ' ') !== draft.attempt.title
        || snapshotJson(draft.document) !== snapshotJson(draft.attempt.document);
      confirmSave(saved);
      return;
    }
    if (draft.baseRevision !== saved.revision) {
      requireResolution();
      return;
    }
    attempt.current = draft.attempt ?? null;
    dirty.current = true;
    setState('editing');
    schedule(debounceMs);
  }

  async function resolveConflict(keepDraft: boolean): Promise<void> {
    const saved = currentHead();
    if (!saved || !isCurrent(saved) || !conflicted.current || inflight.current) return;
    inflight.current = true;
    try {
      const confirmed = await readSaved();
      if (!isCurrent(saved)) return;
      if (confirmed.id !== saved.id || confirmed.owner_id !== saved.owner_id) { onExpired(); return; }
      head.current = confirmed;
      attempt.current = null;
      conflicted.current = false;
      if (keepDraft) {
        preserveDraft(confirmed);
        confirmedRef.current?.(confirmed);
        schedule(0);
      } else {
        clearDraft(saved.owner_id, saved.id, draftKind);
        onDiscard?.(confirmed);
        dirty.current = false;
      }
      setState('editing');
    } catch (error) {
      if (!isCurrent(saved)) return;
      if (error instanceof ApiError && [401, 403].includes(error.status)) { onExpired(); return; }
      throw error;
    } finally {
      inflight.current = false;
    }
  }

  /** Serialize evidence and version writes with autosave, preserving any edits made while they run. */
  async function applyExternalWrite(write: (saved: T) => Promise<T>, apply: (confirmed: T) => void) {
    const saved = currentHead();
    if (!saved || !isCurrent(saved) || dirty.current || attempt.current || conflicted.current || inflight.current) {
      return false;
    }
    inflight.current = true;
    try {
      const confirmed = await write(saved);
      if (!isCurrent(saved)) return true;
      if (confirmed.id !== saved.id || confirmed.owner_id !== saved.owner_id) { onExpired(); return true; }
      if (!dirty.current) {
        head.current = confirmed;
        apply(confirmed);
      }
      return true;
    } finally {
      inflight.current = false;
      if (isCurrent(saved) && dirty.current) requireResolution();
    }
  }

  return {
    state, restoreDraft, saveNow, markDirty, applyExternalWrite,
    resolveByReload: () => resolveConflict(false), resolveByKeep: () => resolveConflict(true),
  };
}
