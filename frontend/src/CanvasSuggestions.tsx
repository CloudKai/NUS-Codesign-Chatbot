/** Editable structured canvas suggestion cards: nothing saves until the student confirms.
 *
 * Proposals are untrusted preview data. Accepting runs the ordinary
 * revision-guarded canvas save (fresh read, conditional PUT) and reuse of the
 * 409 machinery; rejecting or dismissing persists nothing. A stable
 * per-thread record of handled suggestion ids stops a replayed or recovered
 * turn from offering the same proposal twice.
 */
import { useEffect, useRef, useState } from 'react';
import { Icon } from './Icon';
import { ApiError, CANVAS_NODE_KINDS, CANVAS_RELATIONS,
  type CanvasGraph, type CanvasNodeKind, type CanvasRelation,
  type CanvasSuggestion } from './api';
import { readCanvas, saveCanvas } from './api/client';
import { ModalDialog } from './ModalDialog';

const KIND_LABELS: Record<string, string> = {
  note: 'Note', problem: 'Problem', stakeholder: 'Stakeholder', need: 'User need',
  evidence: 'Evidence', assumption: 'Assumption', constraint: 'Constraint', concept: 'Concept',
  specification: 'Specification', ethics: 'Ethics', evaluation: 'Evaluation', reflection: 'Reflection',
};
const RELATION_LABELS: Record<string, string> = {
  supports: 'supports', addresses: 'addresses', depends_on: 'depends on',
  conflicts_with: 'conflicts with', requires: 'requires', derived_from: 'derived from',
  alternative_to: 'alternative to', evaluated_against: 'is evaluated against',
  raises_concern: 'raises a concern about',
};

function handledKey(owner: string, threadId: string) {
  return `codesign-suggestions:${owner || 'session'}:${threadId}`;
}

function readHandled(owner: string, threadId: string): string[] {
  try {
    const value = JSON.parse(sessionStorage.getItem(handledKey(owner, threadId)) || '[]');
    return Array.isArray(value) ? value.filter(item => typeof item === 'string') : [];
  } catch { return []; }
}

/** Preview one turn's canvas proposals and apply only explicit acceptance. */
export function CanvasSuggestions({ threadId, owner = '', suggestions, disabled }: {
  threadId: string; owner?: string; suggestions: CanvasSuggestion[]; disabled?: boolean;
}) {
  const [handled, setHandled] = useState<string[]>(() => readHandled(owner, threadId));
  const [editing, setEditing] = useState<CanvasSuggestion | null>(null);
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [explanation, setExplanation] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const controller = useRef(new AbortController());
  const reviewControl = useRef<HTMLButtonElement>(null);
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

  function openReview(suggestion: CanvasSuggestion) {
    setEditing(suggestion);
    setTitle(suggestion.title ?? '');
    setDescription(suggestion.description ?? '');
    setExplanation(suggestion.explanation ?? '');
    setError('');
    setNotice('');
  }

  function closeReview() {
    setEditing(null);
    setError('');
    setNotice('');
    // The dialog replaces this card's own review control, so native focus
    // restore has no live opener: return focus to it explicitly.
    window.requestAnimationFrame(() => reviewControl.current?.focus());
  }

  /** Confirmation is the only writer: fresh revision, bounded proposal content, conditional save. */
  async function confirm(suggestion: CanvasSuggestion) {
    if (!suggestion.base_canvas_id || busy) return;
    setBusy(true); setError('');
    try {
      const fresh = await readCanvas(threadId, suggestion.base_canvas_id, controller.current.signal);
      if (fresh.graph.accepted_suggestion_ids?.includes(suggestion.id)) {
        // Already saved by another session: say so instead of closing silently.
        markHandled(suggestion.id);
        setNotice('This suggestion was already applied.');
        return;
      }
      if ((fresh.graph.accepted_suggestion_ids?.length ?? 0) >= 1_000) {
        setError('This canvas has reached its saved suggestion limit. Continue editing it manually or create another canvas.');
        return;
      }
      let graph: CanvasGraph;
      if (suggestion.kind === 'new_edge' && suggestion.source_node_id && suggestion.target_node_id) {
        const relation = (suggestion.relation && (CANVAS_RELATIONS as readonly string[]).includes(suggestion.relation)
          ? suggestion.relation : 'supports') as CanvasRelation;
        graph = { ...fresh.graph, edges: [...fresh.graph.edges, {
          id: `e-${Math.random().toString(36).slice(2, 10)}`,
          source: suggestion.source_node_id, target: suggestion.target_node_id,
          relation, explanation: explanation.trim().slice(0, 2000),
        }] };
      } else {
        const nodeKind = (suggestion.node_kind && (CANVAS_NODE_KINDS as readonly string[]).includes(suggestion.node_kind)
          ? suggestion.node_kind : 'note') as CanvasNodeKind;
        const node = {
          id: `n-${Math.random().toString(36).slice(2, 10)}`,
          kind: nodeKind, title: title.trim().slice(0, 200) || 'Coach suggestion',
          description: description.trim().slice(0, 2000),
          x: 60 + fresh.graph.nodes.length * 24, y: 60 + fresh.graph.nodes.length * 24,
        };
        graph = { ...fresh.graph, nodes: [...fresh.graph.nodes, node] };
      }
      graph.accepted_suggestion_ids = [...(fresh.graph.accepted_suggestion_ids ?? []), suggestion.id];
      await saveCanvas(threadId, suggestion.base_canvas_id, graph, fresh.revision, null, controller.current.signal);
      markHandled(suggestion.id);
      closeReview();
    } catch (caught) {
      if (caught instanceof ApiError && [401, 403].includes(caught.status)) { closeReview(); return; }
      if (caught instanceof ApiError && caught.status === 409) {
        setError('That canvas just changed. Nothing was saved — try again to add it to the saved version.');
        return;
      }
      if (caught instanceof ApiError && caught.status === 422) {
        setError('That proposal no longer fits the saved canvas (unknown node or content). Nothing was saved.');
        return;
      }
      setError('Could not confirm whether the suggestion was saved. Try again to check the saved canvas before applying it.');
    } finally { setBusy(false); }
  }

  const pending = suggestions.filter(suggestion =>
    suggestion.base_canvas_id && !handled.includes(suggestion.id));
  if (!pending.length && !editing) return null;

  return <div className="canvas-suggestions" aria-label="Coach canvas suggestions">
    {pending.map(suggestion => {
      const heading = suggestion.kind === 'new_edge'
        ? `Suggested relationship: ${RELATION_LABELS[suggestion.relation ?? ''] ?? suggestion.relation}`
        : `Suggested ${KIND_LABELS[suggestion.node_kind ?? ''] ?? 'node'}: ${suggestion.title}`;
      return <div className="suggestion-card" key={suggestion.id}>
        <p className="suggestion-heading">{heading}</p>
        {suggestion.kind === 'new_edge'
          ? <p className="supporting">{suggestion.source_node_id} → {suggestion.target_node_id}</p>
          : null}
        {suggestion.description ? <p className="supporting">{suggestion.description}</p> : null}
        <p className="supporting suggestion-why">{suggestion.rationale}</p>
        <div className="suggestion-actions">
          <button className="primary" ref={reviewControl} disabled={disabled}
            onClick={() => openReview(suggestion)}>Review suggestion</button>
          <button disabled={disabled} onClick={() => markHandled(suggestion.id)}>Reject suggestion</button>
          <button disabled={disabled} onClick={() => markHandled(suggestion.id)}>Dismiss suggestion</button>
        </div>
      </div>;
    })}
    {editing ? <ModalDialog label="Review coach suggestion" onClose={closeReview}>
      <h2>Review suggestion</h2>
      <p className="supporting">{editing.rationale}</p>
      {error ? <p role="alert">{error}</p> : null}
      {notice ? <p role="status">{notice}</p> : null}
      {editing.kind === 'new_edge'
        ? <>
          <p className="supporting">{editing.source_node_id} — {RELATION_LABELS[editing.relation ?? ''] ?? editing.relation} — {editing.target_node_id}</p>
          <label htmlFor="suggestion-explanation">Relationship note</label>
          <textarea id="suggestion-explanation" maxLength={2000} rows={3} value={explanation}
            onChange={event => setExplanation(event.target.value)}/>
        </>
        : <>
          <label htmlFor="suggestion-kind">Node type</label>
          <select id="suggestion-kind" defaultValue={editing.node_kind ?? 'note'}
            onChange={event => setEditing({ ...editing, node_kind: event.target.value })}>
            {CANVAS_NODE_KINDS.map(option => <option key={option} value={option}>{KIND_LABELS[option]}</option>)}
          </select>
          <label htmlFor="suggestion-title">Node title</label>
          <input id="suggestion-title" maxLength={200} value={title}
            onChange={event => setTitle(event.target.value)}/>
          <label htmlFor="suggestion-description">Content</label>
          <textarea id="suggestion-description" maxLength={2000} rows={4} value={description}
            onChange={event => setDescription(event.target.value)}/>
        </>}
      <p className="supporting">Nothing is saved until you confirm. The canvas keeps its version history.</p>
      <div className="entry-actions">
        <button className="primary" disabled={busy || Boolean(notice) || (editing.kind === 'new_node' && !title.trim())}
          onClick={() => void confirm(editing)}>{busy ? 'Adding…' : 'Add to canvas'}</button>
        <button onClick={closeReview}>Cancel</button>
      </div>
      <button className="icon-button dialog-close" aria-label="Close" onClick={closeReview}><Icon name="close"/></button>
    </ModalDialog> : null}
  </div>;
}
