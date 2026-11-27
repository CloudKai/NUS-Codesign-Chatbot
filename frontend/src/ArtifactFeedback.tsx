/** Before/after artifact feedback card: nothing saves until the student confirms.
 *
 * The proposal is untrusted preview data. Accepting runs the ordinary
 * revision-guarded artifact save (fresh read, conditional PUT — the same 409
 * machinery as editor autosave); rejecting persists nothing. A stable
 * per-thread record of handled proposal ids stops a replayed or recovered
 * turn from offering the same before/after pair twice. Accepted edits keep
 * every earlier version in the artifact's existing history.
 */
import { useEffect, useRef, useState } from 'react';
import { Icon } from './Icon';
import { ModalDialog } from './ModalDialog';
import { ApiError, type ArtifactDocument, type ArtifactFeedback } from './api';
import { readArtifact, saveArtifact } from './api/client';

function handledKey(owner: string, threadId: string) {
  return `codesign-artifact-feedback:${owner || 'session'}:${threadId}`;
}

function readHandled(owner: string, threadId: string): string[] {
  try {
    const value = JSON.parse(sessionStorage.getItem(handledKey(owner, threadId)) || '[]');
    return Array.isArray(value) ? value.filter(item => typeof item === 'string') : [];
  } catch { return []; }
}

/** Replace the text of one top-level block, keeping its node type. */
function replaceBlockText(document: ArtifactDocument, paragraph: number,
                          text: string): ArtifactDocument | null {
  const blocks = Array.isArray(document.content) ? [...document.content] : [];
  const block = blocks[paragraph];
  if (!block || typeof block !== 'object') return null;
  const record = block as { type?: string; content?: unknown };
  if (!['paragraph', 'heading', 'codeBlock'].includes(String(record.type))) return null;
  blocks[paragraph] = { ...record, content: [{ type: 'text', text }] };
  return { ...document, content: blocks };
}

/** Build an explicit reviewed document from accepted whole-document text. */
function documentFromText(text: string): ArtifactDocument {
  const paragraphs = text.split(/\n{2,}/).map(part => part.trim()).filter(Boolean);
  return { type: 'doc', content: paragraphs.map(part => ({
    type: 'paragraph', content: [{ type: 'text', text: part }],
  })) };
}

/** Preview one before/after pair and apply only explicit acceptance. */
export function ArtifactFeedbackCard({ threadId, owner = '', feedback, disabled }: {
  threadId: string; owner?: string; feedback: ArtifactFeedback; disabled?: boolean;
}) {
  const [handled, setHandled] = useState<string[]>(() => readHandled(owner, threadId));
  const [editing, setEditing] = useState(false);
  const reviewControl = useRef<HTMLButtonElement>(null);
  const [text, setText] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const controller = useRef(new AbortController());
  useEffect(() => () => controller.current.abort(), []);

  function markHandled(id: string) {
    const next = [...readHandled(owner, threadId)];
    if (!next.includes(id)) {
      next.push(id);
      try { sessionStorage.setItem(handledKey(owner, threadId), JSON.stringify(next)); }
      catch { /* Acceptance still works in memory when tab storage is unavailable. */ }
    }
    setHandled(next);
  }

  function openReview() {
    setEditing(true);
    setText(feedback.proposed_text);
    setError('');
  }

  /** The dialog replaces this card's review control, so return focus to it explicitly. */
  function closeReview() {
    setEditing(false);
    setError('');
    window.requestAnimationFrame(() => reviewControl.current?.focus());
  }

  /** Confirmation is the only writer: fresh revision, reviewed text, conditional save. */
  async function confirm() {
    const artifactId = feedback.base_artifact_id;
    if (!artifactId || busy) return;
    setBusy(true); setError('');
    try {
      const fresh = await readArtifact(threadId, artifactId, controller.current.signal);
      if (fresh.revision !== feedback.base_artifact_revision) {
        setError('This document has changed since the feedback was generated. Your saved writing is preserved. Copy any useful suggestion into the editor or request feedback on the current version.');
        return;
      }
      let document: ArtifactDocument | null;
      if (feedback.paragraph === null || feedback.paragraph === undefined) {
        document = documentFromText(text.trim());
      } else {
        document = replaceBlockText(fresh.document, feedback.paragraph, text.trim());
        if (document === null) {
          setError('That passage type cannot be edited automatically here. You can copy the suggestion into the editor.');
          return;
        }
      }
      await saveArtifact(threadId, artifactId, document, fresh.revision, null, controller.current.signal);
      markHandled(feedback.id);
      setEditing(false);
    } catch (caught) {
      if (caught instanceof ApiError && [401, 403].includes(caught.status)) { setEditing(false); return; }
      if (caught instanceof ApiError && caught.status === 409) {
        setError('That document just changed. Nothing was saved — try again to apply it to the saved version.');
        return;
      }
      setError('Could not apply the feedback. Nothing was saved. Try again.');
    } finally { setBusy(false); }
  }

  if (handled.includes(feedback.id)) return null;

  return <div className="artifact-feedback" aria-label="Coach document feedback">
    {!editing ? <>
      <div className="feedback-compare">
        <div className="feedback-side">
          <p className="feedback-label">In your draft</p>
          <blockquote>{feedback.original_text || '(no saved text resolved)'}</blockquote>
        </div>
        <div className="feedback-side">
          <p className="feedback-label">Suggested revision</p>
          <blockquote>{feedback.proposed_text}</blockquote>
        </div>
      </div>
      <p className="supporting suggestion-why">{feedback.rationale}</p>
      <div className="suggestion-actions">
        <button className="primary" ref={reviewControl} disabled={disabled} onClick={openReview}>Review suggestion</button>
        <button disabled={disabled} onClick={() => markHandled(feedback.id)}>Reject suggestion</button>
      </div>
    </> : <ModalDialog label="Review coach feedback" onClose={closeReview}>
      <h2>Review suggested revision</h2>
      <p className="supporting">{feedback.rationale}</p>
      {error ? <p role="alert">{error}</p> : null}
      <p className="feedback-label">In your draft</p>
      <blockquote>{feedback.original_text || '(no saved text resolved)'}</blockquote>
      <label htmlFor="artifact-feedback-text">Revised text</label>
      <textarea id="artifact-feedback-text" maxLength={8000} rows={6} value={text}
        onChange={event => setText(event.target.value)}/>
      <p className="supporting">Nothing is saved until you confirm. The document keeps its version history, and you can restore any earlier version.</p>
      <div className="entry-actions">
        <button className="primary" disabled={busy || !text.trim()}
          onClick={() => void confirm()}>{busy ? 'Applying…' : 'Apply to document'}</button>
        <button onClick={closeReview}>Cancel</button>
      </div>
      <button className="icon-button dialog-close" aria-label="Close"
        onClick={closeReview}><Icon name="close"/></button>
    </ModalDialog>}
  </div>;
}
