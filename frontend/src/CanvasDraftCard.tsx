/** Reviewable canvas draft card: confirmation always creates a NEW artifact.
 *
 * The synthesized draft is untrusted preview data. Confirming runs the
 * ordinary authorized artifact create — never an overwrite — with the
 * contributing node ids and their evidence attached as provenance
 * references. A stale canvas snapshot warns but still defers to the
 * student's explicit confirmation; an unavailable canvas blocks with nothing
 * created. Rejecting persists nothing, and a handled draft id is never
 * offered twice.
 */
import { useEffect, useRef, useState } from 'react';
import { Icon } from './Icon';
import { ModalDialog } from './ModalDialog';
import { ApiError, type ArtifactDocument, type CanvasDraft } from './api';
import { createArtifact, readCanvas } from './api/client';

function handledKey(owner: string, threadId: string) {
  return `codesign-canvas-drafts:${owner || 'session'}:${threadId}`;
}

function readHandled(owner: string, threadId: string): string[] {
  try {
    const value = JSON.parse(sessionStorage.getItem(handledKey(owner, threadId)) || '[]');
    return Array.isArray(value) ? value.filter(item => typeof item === 'string') : [];
  } catch { return []; }
}

function documentFromText(text: string): ArtifactDocument {
  const paragraphs = text.split(/\n{2,}/).map(part => part.trim()).filter(Boolean);
  return { type: 'doc', content: paragraphs.length
    ? paragraphs.map(part => ({ type: 'paragraph', content: [{ type: 'text', text: part }] }))
    : [{ type: 'paragraph', content: [{ type: 'text', text: text.trim() || '(empty draft)' }] }] };
}

/** Preview one synthesized draft and create a new artifact only on confirmation. */
export function CanvasDraftCard({ threadId, owner = '', draft, disabled }: {
  threadId: string; owner?: string; draft: CanvasDraft; disabled?: boolean;
}) {
  const [handled, setHandled] = useState<string[]>(() => readHandled(owner, threadId));
  const [editing, setEditing] = useState(false);
  const reviewControl = useRef<HTMLButtonElement>(null);
  const [title, setTitle] = useState(draft.title);
  const [text, setText] = useState(draft.draft_text);
  const [stale, setStale] = useState(false);
  const [frozen, setFrozen] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const controller = useRef(new AbortController());
  useEffect(() => () => controller.current.abort(), []);

  /** The dialog replaces this card's review control, so return focus to it explicitly. */
  function closeReview() {
    setEditing(false);
    setError('');
    setStale(false);
    window.requestAnimationFrame(() => reviewControl.current?.focus());
  }

  function markHandled(id: string) {
    const next = [...readHandled(owner, threadId)];
    if (!next.includes(id)) {
      next.push(id);
      try { sessionStorage.setItem(handledKey(owner, threadId), JSON.stringify(next)); }
      catch { /* Confirmation still works in memory when tab storage is unavailable. */ }
    }
    setHandled(next);
  }

  /** Confirmation is the only writer, and it always creates a new artifact. */
  async function confirm() {
    const canvasId = draft.base_canvas_id;
    if (!canvasId || busy) return;
    setBusy(true); setError('');
    try {
      const fresh = await readCanvas(threadId, canvasId, controller.current.signal);
      setStale(fresh.revision !== draft.base_canvas_revision);
      if (fresh.revision !== draft.base_canvas_revision && !stale) {
        // First look: tell the student the snapshot moved and wait for a
        // deliberate second confirmation instead of deciding for them.
        setError('The canvas changed since this draft was written. Review the draft, then confirm again to create the artifact anyway.');
        return;
      }
      // Provenance: contributing nodes (with the canvas revision they came
      // from) plus their resolved evidence links.
      const nodeReferences = (draft.node_ids ?? []).map(nodeId => ({
        kind: 'canvas_node' as const, id: nodeId, canvas_id: canvasId,
        revision: draft.base_canvas_revision ?? undefined,
      }));
      const evidence = fresh.graph.nodes
        .filter(node => (draft.node_ids ?? []).includes(node.id))
        .flatMap(node => (node.references ?? [])
          .filter(reference => reference.kind === 'source')
          .map(reference => ({ kind: 'source' as const, id: reference.id })));
      // The saved draft id is stable across sessions, so a safe retry replays
      // rather than creating a duplicate. AI provenance is recorded explicitly.
      await createArtifact(threadId, title.trim().slice(0, 200) || 'Draft from canvas',
        documentFromText(text), controller.current.signal, 'notes',
        [...nodeReferences, ...evidence], `draft:${draft.id}`, 'coach_draft');
      markHandled(draft.id);
      setEditing(false);
      setStale(false);
    } catch (caught) {
      if (caught instanceof ApiError && [401, 403].includes(caught.status)) { setEditing(false); return; }
      if (caught instanceof ApiError && caught.status === 404) {
        setError('That canvas is no longer available. Nothing was created.');
        return;
      }
      if (caught instanceof ApiError && caught.status === 422) {
        setError('This draft could not be created. An earlier attempt may already have saved it — check your documents before trying again, or copy the draft into a new artifact manually.');
        return;
      }
      // The create may have committed even though the acknowledgement was
      // lost. The deterministic request id makes a retry replay safely, so the
      // editable payload is frozen: a retry is provably the same request.
      setFrozen(true);
      setError("We couldn't confirm whether the artifact was created. Check your documents before trying again; a retry is safe and will not duplicate it.");
    } finally { setBusy(false); }
  }

  if (handled.includes(draft.id)) return null;

  return <div className="canvas-draft" aria-label="Coach draft from canvas nodes">
    {!editing ? <>
      <p className="suggestion-heading">Suggested draft: {draft.title}</p>
      <p className="supporting">From {(draft.node_ids ?? []).length} selected canvas node{(draft.node_ids ?? []).length === 1 ? '' : 's'} · coach-synthesized for your review</p>
      <blockquote className="draft-preview">{draft.draft_text}</blockquote>
      {draft.rationale ? <p className="supporting suggestion-why">{draft.rationale}</p> : null}
      <div className="suggestion-actions">
        <button className="primary" ref={reviewControl} disabled={disabled} onClick={() => {
          setEditing(true); setTitle(draft.title); setText(draft.draft_text);
          setStale(false); setError('');
        }}>Review draft</button>
        <button disabled={disabled} onClick={() => markHandled(draft.id)}>Reject draft</button>
      </div>
    </> : <ModalDialog label="Review canvas draft" onClose={closeReview}>
      <h2>Review suggested draft</h2>
      <p className="supporting">Confirming creates a new artifact — it never overwrites an existing one. Contributing node links and their evidence stay attached.</p>
      {error ? <p role="alert">{error}</p> : null}
      {stale ? <p role="status" className="supporting">The canvas changed since this draft was written. The draft text was not updated — check it before creating.</p> : null}
      <label htmlFor="canvas-draft-title">Artifact title</label>
      <input id="canvas-draft-title" maxLength={200} value={title} disabled={frozen}
        onChange={event => setTitle(event.target.value)}/>
      <label htmlFor="canvas-draft-text">Draft text</label>
      <textarea id="canvas-draft-text" maxLength={8000} rows={8} value={text} disabled={frozen}
        onChange={event => setText(event.target.value)}/>
      <div className="entry-actions">
        <button className="primary" disabled={busy || !text.trim() || !title.trim()}
          onClick={() => void confirm()}>{busy ? 'Creating…' : 'Create new artifact'}</button>
        <button onClick={closeReview}>Cancel</button>
      </div>
      <button className="icon-button dialog-close" aria-label="Close"
        onClick={closeReview}><Icon name="close"/></button>
    </ModalDialog>}
  </div>;
}
