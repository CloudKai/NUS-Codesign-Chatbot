/**
 * @vitest-environment jsdom
 */
/** Debounced deduplicated autosave: states, conflict preservation, deduplication and write amplification. */
import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { AUTOSAVE_DEBOUNCE_MS, draftKey, readDraft, useArtifactAutosave } from './useArtifactAutosave';
import { ApiError, type Artifact } from './api';

function artifact(revision: number): Artifact {
  return { owner_id: 'a', thread_id: 't1', id: 'doc-1', title: 'Notes', kind: 'notes',
    document: { type: 'doc', content: [] }, schema_version: 1, revision,
    origin: 'editor', created_at: '2026-11-24T00:00:00Z', updated_at: '2026-11-24T00:00:00Z',
    references: [] };
}

const document = { type: 'doc', content: [] };

function setup(onSave?: (document: unknown, title: string, revision: number) => Promise<Artifact>) {
  let current = artifact(1);
  const onReload = vi.fn(async () => artifact(9));
  const onExpired = vi.fn();
  /** Commit the confirmed revision like the real editor does after a successful save. */
  const confirm = (revision: number) => { current = artifact(revision); hook.rerender(); };
  const saving = onSave ?? vi.fn(async (_document: unknown, _title: string, revision: number) => artifact(revision + 1));
  const hook = renderHook(() => useArtifactAutosave({
    owner: 'a', artifact: current, document: () => document, title: () => 'Notes', onSave: saving, readSaved: onReload, onExpired,
    getSavedDocument: value => value.document,
    enabled: true, debounceMs: 20,
  }));
  /** Flush the debounce timer and every resulting save promise. */
  const settle = async (ms: number) => {
    await act(async () => { vi.advanceTimersByTime(ms); });
  };
  return { hook, onSave: saving, onReload, onExpired, settle, confirm };
}

beforeEach(() => { vi.useFakeTimers(); });
afterEach(() => { vi.useRealTimers(); sessionStorage.clear(); });

it('saves once after the debounce settles and reports Saved with the confirmed revision', async () => {
  const { hook, onSave, settle } = setup();
  act(() => hook.result.current.markDirty());
  expect(hook.result.current.state).toBe('editing');
  await settle(AUTOSAVE_DEBOUNCE_MS + 10);
  expect(hook.result.current.state).toBe('saved');
  expect(onSave).toHaveBeenCalledTimes(1);
  expect(onSave).toHaveBeenCalledWith(document, 'Notes', 1);
});

it('reconciles the confirmed revision through onConfirmed so the next save never goes stale', async () => {
  // The component wires onConfirmed to its own state update; no manual confirm() between saves.
  let current = artifact(1);
  const onReload = vi.fn(async () => artifact(9));
  const saving = vi.fn(async (_document: unknown, _title: string, revision: number) => artifact(revision + 1));
  const hook = renderHook(() => useArtifactAutosave({
    owner: 'a', artifact: current, document: () => document, title: () => 'Notes', onSave: saving,
    readSaved: onReload, onExpired: vi.fn(), enabled: true, debounceMs: 20,
    getSavedDocument: value => value.document,
    onConfirmed: confirmed => { current = confirmed; },
  }));
  const settle = async (ms: number) => {
    await act(async () => { vi.advanceTimersByTime(ms); });
  };
  // The subject prop changes only through the component's own onConfirmed state update.
  hook.rerender();
  act(() => hook.result.current.markDirty());
  await settle(AUTOSAVE_DEBOUNCE_MS + 10);
  act(() => hook.result.current.markDirty());
  await settle(AUTOSAVE_DEBOUNCE_MS + 10);
  await settle(30);
  const revisions = saving.mock.calls.map(call => call[2] as number);
  expect(revisions).toEqual([1, 2]); // The second autosave carries the confirmed revision, not a stale one.
  expect(hook.result.current.state).toBe('saved');
});

it('collapses a burst of edits into one checkpoint and deduplicates an in-flight save', async () => {
  const onSave = vi.fn(async (_document: unknown, _title: string, revision: number) => artifact(revision + 1));
  const { hook, settle, confirm } = setup(onSave);
  act(() => { hook.result.current.markDirty(); vi.advanceTimersByTime(10); hook.result.current.markDirty(); });
  await settle(10);
  act(() => { hook.result.current.markDirty(); });
  await settle(AUTOSAVE_DEBOUNCE_MS + 10);
  await settle(30);
  expect(hook.result.current.state).toBe('saved');
  expect(onSave).toHaveBeenCalledTimes(1);
  confirm(2); // The editor commits the confirmed revision like the real component.
  act(() => { hook.result.current.markDirty(); });
  await settle(30);
  expect(onSave).toHaveBeenCalledTimes(2);
  const revisions = onSave.mock.calls.map(call => call[2] as number);
  expect(revisions).toEqual([1, 2]); // The trailing save carries the confirmed revision, never a duplicate.
  expect(hook.result.current.state).toBe('saved');
});

it('distinguishes offline and failure states', async () => {
  const offline = setup(vi.fn(async () => { throw new TypeError('fetch failed'); }));
  act(() => offline.hook.result.current.markDirty());
  await offline.settle(AUTOSAVE_DEBOUNCE_MS + 10);
  expect(offline.hook.result.current.state).toBe('offline');
  expect(offline.onSave).toHaveBeenCalledTimes(1);

  const failing = setup(async () => { throw new ApiError(503); });
  act(() => failing.hook.result.current.markDirty());
  await failing.settle(AUTOSAVE_DEBOUNCE_MS + 10);
  expect(failing.hook.result.current.state).toBe('failure');
});

it('keeps the losing draft on a conflict and resolves only explicitly', async () => {
  const { hook, onReload, settle } = setup(async () => { throw new ApiError(409); });
  act(() => hook.result.current.markDirty());
  await settle(AUTOSAVE_DEBOUNCE_MS + 10);
  expect(hook.result.current.state).toBe('conflict');
  // The losing local draft stays persisted for this owner only.
  expect(readDraft('a', 'doc-1')).toMatchObject({ document, title: 'Notes', baseRevision: 1 });
  act(() => { hook.result.current.markDirty(); });
  expect(hook.result.current.state).toBe('conflict'); // No blind retry while conflicting.
  await act(async () => { await hook.result.current.resolveByReload(); });
  expect(onReload).toHaveBeenCalledTimes(1);
  expect(hook.result.current.state).toBe('editing');
  expect(readDraft('a', 'doc-1')).toBeNull();
});

it('stores drafts owner-scoped and clears them after a confirmed save', async () => {
  const { hook, settle } = setup();
  act(() => hook.result.current.markDirty());
  await settle(AUTOSAVE_DEBOUNCE_MS + 10);
  expect(hook.result.current.state).toBe('saved');
  expect(readDraft('a', 'doc-1')).toBeNull();
  act(() => { hook.result.current.markDirty(); });
  await settle(10); // Mid-debounce: the draft checkpoint exists for refresh recovery.
  expect(sessionStorage.getItem(draftKey('a', 'doc-1'))).toBeTruthy();
  expect(sessionStorage.getItem(draftKey('b', 'doc-1'))).toBeNull();
});

it('keeps edits made during an in-flight save recoverable after its acknowledgement', async () => {
  let confirmSave!: (value: Artifact) => void;
  const saving = new Promise<Artifact>(resolve => { confirmSave = resolve; });
  const { hook } = setup(() => saving);
  act(() => hook.result.current.saveNow());
  act(() => hook.result.current.markDirty());
  await act(async () => confirmSave(artifact(2)));
  expect(readDraft('a', 'doc-1')).toMatchObject({ document, title: 'Notes', baseRevision: 2 });
  expect(hook.result.current.state).toBe('editing');
});

it('pauses a pending autosave and subsequent edits after a conflict', async () => {
  let rejectSave!: (error: Error) => void;
  const saving = new Promise<Artifact>((_resolve, reject) => { rejectSave = reject; });
  const onSave = vi.fn(() => saving);
  const { hook, settle } = setup(onSave);
  act(() => hook.result.current.saveNow());
  act(() => hook.result.current.markDirty());
  await act(async () => rejectSave(new ApiError(409)));
  await settle(100);
  act(() => hook.result.current.markDirty());
  await settle(100);
  expect(hook.result.current.state).toBe('conflict');
  expect(onSave).toHaveBeenCalledTimes(1);
});

it('recovers a committed save acknowledgement by reading the saved revision', async () => {
  const onSave = vi.fn(async () => { throw new TypeError('connection closed'); });
  const { hook, onReload } = setup(onSave);
  onReload.mockResolvedValue(artifact(2));
  await act(async () => hook.result.current.saveNow());
  expect(hook.result.current.state).toBe('offline');
  await act(async () => hook.result.current.saveNow());
  expect(onReload).toHaveBeenCalledTimes(1);
  expect(onSave).toHaveBeenCalledTimes(1);
  expect(hook.result.current.state).toBe('saved');
  expect(readDraft('a', 'doc-1')).toBeNull();
});

it('leaves the original owner’s draft recoverable when a response arrives after navigation', async () => {
  let confirmSave!: (value: Artifact) => void;
  const saving = new Promise<Artifact>(resolve => { confirmSave = resolve; });
  const { hook } = setup(() => saving);
  act(() => hook.result.current.saveNow());
  hook.unmount();
  await act(async () => confirmSave(artifact(2)));
  expect(readDraft('a', 'doc-1')).toMatchObject({ baseRevision: 1 });
  expect(readDraft('b', 'doc-1')).toBeNull();
});

it('does not autosave while disabled', async () => {
  let current = artifact(1);
  const onSave = vi.fn(async () => { current = artifact(2); return current; });
  const hook = renderHook(() => useArtifactAutosave({
    owner: 'a', artifact: current, document: () => document, title: () => 'Notes', onSave, readSaved: vi.fn(),
    getSavedDocument: value => value.document,
    onExpired: vi.fn(), enabled: false, debounceMs: 20,
  }));
  act(() => hook.result.current.markDirty());
  await act(async () => { vi.advanceTimersByTime(200); });
  expect(onSave).not.toHaveBeenCalled();
});
