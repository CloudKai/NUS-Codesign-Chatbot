/** Editable chat-to-canvas node proposal: nothing saves until the student confirms. */
import { useEffect, useRef, useState } from 'react';
import { Icon } from './Icon';
import { ModalDialog } from './ModalDialog';
import { ApiError, CANVAS_NODE_KINDS,
  type CanvasGraph, type CanvasNodeKind } from './api';
import { readCanvas, readCanvases, saveCanvas } from './api/client';

const KIND_LABELS: Record<string, string> = {
  note: 'Note', problem: 'Problem', stakeholder: 'Stakeholder', need: 'User need',
  evidence: 'Evidence', assumption: 'Assumption', constraint: 'Constraint', concept: 'Concept',
  specification: 'Specification', ethics: 'Ethics', evaluation: 'Evaluation', reflection: 'Reflection',
};

/** Turn one selected message into an editable node on a chosen canvas. */
export function ChatToCanvasProposal({ threadId, messageId, content, onClose, onCreated }: {
  threadId: string; messageId: string; content: string;
  onClose: () => void; onCreated: (canvasId: string) => void;
}) {
  const [canvases, setCanvases] = useState<{ id: string; title: string }[] | null>(null);
  const [destination, setDestination] = useState('');
  const [kind, setKind] = useState<CanvasNodeKind>('note');
  const [title, setTitle] = useState(() => `${content.trim().slice(0, 60)}${content.trim().length > 60 ? '…' : ''}`);
  const [description, setDescription] = useState(content.trim());
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const controller = useRef(new AbortController());
  useEffect(() => () => controller.current.abort(), []);

  useEffect(() => {
    readCanvases(threadId, controller.current.signal)
      .then(list => {
        setCanvases(list.canvases);
        if (list.canvases.length === 1) setDestination(list.canvases[0].id);
      })
      .catch(error => {
        if (error instanceof ApiError && [401, 403].includes(error.status)) { onClose(); return; }
        setError('Could not load your canvases. Try again.');
      });
  }, [threadId]);

  /** Confirmation is the only writer: fresh revision, node appended, message reference kept. */
  async function confirm() {
    if (!destination || busy) return;
    setBusy(true); setError('');
    try {
      const fresh = await readCanvas(threadId, destination, controller.current.signal);
      const node = {
        id: `n-${Math.random().toString(36).slice(2, 10)}`,
        kind, title: title.trim().slice(0, 200) || 'From chat',
        description: description.trim().slice(0, 2000),
        x: 60 + fresh.graph.nodes.length * 24, y: 60 + fresh.graph.nodes.length * 24,
        references: [{ kind: 'message' as const, id: messageId }],
      };
      const graph: CanvasGraph = { ...fresh.graph, nodes: [...fresh.graph.nodes, node] };
      await saveCanvas(threadId, destination, graph, fresh.revision, null, controller.current.signal);
      onCreated(destination);
    } catch (error) {
      if (error instanceof ApiError && [401, 403].includes(error.status)) { onClose(); return; }
      if (error instanceof ApiError && error.status === 409) {
        setError('That canvas just changed. Confirm again to add your node to the saved version.');
        return;
      }
      if (error instanceof ApiError && error.status === 422) {
        setError('That content can no longer be linked. It may have been removed.');
        return;
      }
      setError('Could not add the node. Nothing was saved. Try again.');
    } finally { setBusy(false); }
  }

  return <ModalDialog label="Add chat content to a canvas" onClose={onClose}>
    <h2>Add to canvas</h2>
    {error ? <p role="alert">{error}</p> : null}
    {canvases !== null && canvases.length === 0
      ? <p className="supporting">No canvases yet. Create one from your notebook first — nothing is saved until you confirm here.</p>
      : <>
      <label htmlFor="chat-to-canvas-destination">Destination canvas</label>
      <select id="chat-to-canvas-destination" value={destination}
        onChange={event => setDestination(event.target.value)}>
        <option value="">Choose a canvas…</option>
        {(canvases ?? []).map(canvas => <option key={canvas.id} value={canvas.id}>{canvas.title}</option>)}
      </select>
      <label htmlFor="chat-to-canvas-kind">Node type</label>
      <select id="chat-to-canvas-kind" value={kind} onChange={event => setKind(event.target.value as CanvasNodeKind)}>
        {CANVAS_NODE_KINDS.map(option => <option key={option} value={option}>{KIND_LABELS[option]}</option>)}
      </select>
      <label htmlFor="chat-to-canvas-title">Title</label>
      <input id="chat-to-canvas-title" maxLength={200} value={title}
        onChange={event => setTitle(event.target.value)}/>
      <label htmlFor="chat-to-canvas-content">Content</label>
      <textarea id="chat-to-canvas-content" maxLength={2000} rows={4} value={description}
        onChange={event => setDescription(event.target.value)}/>
      <p className="supporting">The saved node keeps a link to the original message. Nothing is saved until you confirm.</p>
      <div className="entry-actions">
        <button className="primary" disabled={!destination || busy || !title.trim()} onClick={() => void confirm()}>
          {busy ? 'Adding…' : 'Add node'}
        </button>
        <button onClick={onClose}>Cancel</button>
      </div>
      </>}
    <button className="icon-button dialog-close" aria-label="Close" onClick={onClose}><Icon name="close"/></button>
  </ModalDialog>;
}
