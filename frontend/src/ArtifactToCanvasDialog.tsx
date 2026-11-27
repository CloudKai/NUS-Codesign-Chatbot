/** Return artifact reasoning to the canvas: create an editable node proposal or
 * explicitly link an existing node, always carrying artifact/revision origin.
 * Nothing saves until the student confirms, and every save is the ordinary
 * revision-guarded canvas save — the artifact itself is never changed.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { Icon } from './Icon';
import { ModalDialog } from './ModalDialog';
import { CANVAS_NODE_KINDS, ApiError, type Artifact,
  type CanvasGraph, type CanvasNodeKind, type EvidenceReference } from './api';
import { readCanvas, readCanvases, saveCanvas } from './api/client';
import { artifactPlainText } from './artifactText';

const KIND_LABELS: Record<string, string> = {
  note: 'Note', problem: 'Problem', stakeholder: 'Stakeholder', need: 'User need',
  evidence: 'Evidence', assumption: 'Assumption', constraint: 'Constraint', concept: 'Concept',
  specification: 'Specification', ethics: 'Ethics', evaluation: 'Evaluation', reflection: 'Reflection',
};

/** Bounded readable text of one top-level document block, mirroring the server projection. */

/** Readable saved text for the chosen source: the whole bounded document or one block. */
function savedText(artifact: Artifact, source: 'document' | number): string {
  return artifactPlainText(artifact.document, source);
}

/** Choose a destination canvas and create a new node there or link an existing one. */
export function ArtifactToCanvasDialog({ threadId, artifact, initialParagraph, onClose, onOpenCanvas }: {
  threadId: string; artifact: Artifact; initialParagraph: number | null;
  onClose: () => void; onOpenCanvas?: (canvasId: string) => void;
}) {
  const [canvases, setCanvases] = useState<{ id: string; title: string }[] | null>(null);
  const [destination, setDestination] = useState('');
  const [source, setSource] = useState<'document' | number>(initialParagraph ?? 'document');
  const [kind, setKind] = useState<CanvasNodeKind>('note');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [proposed, setProposed] = useState(false);
  const [linkNodeId, setLinkNodeId] = useState('');
  const [linkGraph, setLinkGraph] = useState<CanvasGraph | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<string | null>(null);
  const controller = useRef(new AbortController());
  useEffect(() => () => controller.current.abort(), []);

  useEffect(() => {
    readCanvases(threadId, controller.current.signal)
      .then(list => {
        setCanvases(list.canvases);
        if (list.canvases.length === 1) setDestination(list.canvases[0].id);
      })
      .catch(caught => {
        if (caught instanceof ApiError && [401, 403].includes(caught.status)) { onClose(); return; }
        setError('Could not load your canvases. Try again.');
      });
  }, [threadId]);

  /** Load the chosen canvas's graph so linking keeps every existing field. */
  useEffect(() => {
    if (!destination) { setLinkGraph(null); setLinkNodeId(''); return; }
    const request = new AbortController();
    readCanvas(threadId, destination, request.signal)
      .then(canvas => setLinkGraph(canvas.graph))
      .catch(caught => {
        if (request.signal.aborted) return;
        if (caught instanceof ApiError && [401, 403].includes(caught.status)) { onClose(); return; }
        setLinkGraph(null);
        setError('Could not open that canvas. Try again.');
      });
    return () => request.abort();
  }, [destination, threadId]);

  /** The proposal prefills from the saved document, never from unsaved editor edits. */
  const prefill = useMemo(() => {
    const text = savedText(artifact, source);
    const trimmed = text.trim();
    return {
      title: trimmed ? `${trimmed.slice(0, 60)}${trimmed.length > 60 ? '…' : ''}` : `From ${artifact.title}`,
      description: trimmed.slice(0, 2000),
    };
  }, [artifact, source]);

  function showProposal() {
    setTitle(prefill.title);
    setDescription(prefill.description);
    setProposed(true);
  }

  /** Provenance: the saved artifact id and the revision this content came from. */
  function artifactReference(): EvidenceReference {
    return { kind: 'artifact', id: artifact.id, revision: artifact.revision };
  }

  /** Confirmation is the only writer: fresh revision, then the guarded save. */
  async function confirm(graph: CanvasGraph, revision: number): Promise<void> {
    if (!destination) return;
    await saveCanvas(threadId, destination, graph, revision, null, controller.current.signal);
    setDone(destination);
    onOpenCanvas?.(destination);
  }

  async function createNode() {
    if (!destination || busy) return;
    setBusy(true); setError('');
    try {
      const fresh = await readCanvas(threadId, destination, controller.current.signal);
      const node = {
        id: `n-${Math.random().toString(36).slice(2, 10)}`,
        kind, title: title.trim().slice(0, 200) || `From ${artifact.title}`,
        description: description.trim().slice(0, 2000),
        x: 60 + fresh.graph.nodes.length * 24, y: 60 + fresh.graph.nodes.length * 24,
        references: [artifactReference()],
      };
      await confirm({ ...fresh.graph, nodes: [...fresh.graph.nodes, node] }, fresh.revision);
    } catch (caught) {
      handleSaveError(caught);
    } finally { setBusy(false); }
  }

  async function linkNode() {
    if (!destination || !linkGraph || !linkNodeId || busy) return;
    setBusy(true); setError('');
    try {
      const fresh = await readCanvas(threadId, destination, controller.current.signal);
      if (!fresh.graph.nodes.some(node => node.id === linkNodeId)) {
        setLinkGraph(fresh.graph);
        setLinkNodeId('');
        setError('That node was removed. Choose a node from the saved canvas.');
        return;
      }
      const graph: CanvasGraph = {
        ...fresh.graph,
        nodes: fresh.graph.nodes.map(node => node.id === linkNodeId ? {
          ...node,
          references: [...(node.references ?? []).map(entry => ({ ...entry })), artifactReference()],
        } : node),
      };
      await confirm(graph, fresh.revision);
    } catch (caught) {
      handleSaveError(caught);
    } finally { setBusy(false); }
  }

  function handleSaveError(caught: unknown) {
    if (caught instanceof ApiError && [401, 403].includes(caught.status)) { onClose(); return; }
    if (caught instanceof ApiError && caught.status === 409) {
      setError('That canvas just changed. Confirm again to apply this to the saved version.');
      return;
    }
    if (caught instanceof ApiError && caught.status === 422) {
      setError('That link can no longer be saved. It may reference removed work.');
      return;
    }
    setError('Could not update the canvas. Nothing was saved. Try again.');
  }

  return <ModalDialog label="Add document content to a canvas" onClose={onClose}>
    <h2>Add to canvas</h2>
    {done ? <p role="status" className="supporting">The canvas was saved. Open it to keep mapping — this document is unchanged.</p> : null}
    {error ? <p role="alert">{error}</p> : null}
    {canvases !== null && canvases.length === 0
      ? <p className="supporting">No canvases yet. Create one from your notebook first — nothing is saved until you confirm here.</p>
      : <>
      <label htmlFor="artifact-to-canvas-destination">Destination canvas</label>
      <select id="artifact-to-canvas-destination" value={destination}
        onChange={event => { setDestination(event.target.value); setProposed(false); }}>
        <option value="">Choose a canvas…</option>
        {(canvases ?? []).map(canvas => <option key={canvas.id} value={canvas.id}>{canvas.title}</option>)}
      </select>
      <fieldset>
        <legend>Saved content to use</legend>
        <label className="artifact-source-option">
          <input type="radio" name="artifact-source" checked={source === 'document'}
            onChange={() => { setSource('document'); setProposed(false); }}/>
          <span>Whole document</span>
        </label>
        {(artifact.document?.content ?? []).map((_block, index) => (
          <label key={index} className="artifact-source-option">
            <input type="radio" name="artifact-source" checked={source === index}
              onChange={() => { setSource(index); setProposed(false); }}/>
            <span>Paragraph {index + 1}</span>
          </label>
        ))}
      </fieldset>
      {proposed ? <>
        <label htmlFor="artifact-to-canvas-kind">Node type</label>
        <select id="artifact-to-canvas-kind" value={kind}
          onChange={event => setKind(event.target.value as CanvasNodeKind)}>
          {CANVAS_NODE_KINDS.map(option => <option key={option} value={option}>{KIND_LABELS[option]}</option>)}
        </select>
        <label htmlFor="artifact-to-canvas-title">Title</label>
        <input id="artifact-to-canvas-title" maxLength={200} value={title}
          onChange={event => setTitle(event.target.value)}/>
        <label htmlFor="artifact-to-canvas-content">Content</label>
        <textarea id="artifact-to-canvas-content" maxLength={2000} rows={4} value={description}
          onChange={event => setDescription(event.target.value)}/>
        <p className="supporting">The node keeps a link to “{artifact.title}” (saved version {artifact.revision}). Nothing is saved until you confirm.</p>
        <div className="entry-actions">
          <button className="primary" disabled={!destination || busy || !title.trim()}
            onClick={() => void createNode()}>
            {busy ? 'Adding…' : 'Create new node'}
          </button>
          <button onClick={() => setProposed(false)}>Back</button>
        </div>
      </> : <>
        <label htmlFor="artifact-to-canvas-node">Link an existing node instead</label>
        <select id="artifact-to-canvas-node" value={linkNodeId}
          onChange={event => setLinkNodeId(event.target.value)}>
          <option value="">Choose a node…</option>
          {(linkGraph?.nodes ?? []).map(node =>
            <option key={node.id} value={node.id}>{KIND_LABELS[node.kind] ?? node.kind}: {node.title}</option>)}
        </select>
        <p className="supporting">Creating prefills an editable node from the saved document text; linking attaches this document (saved version {artifact.revision}) to an existing node without touching its other fields.</p>
        <div className="entry-actions">
          <button disabled={!destination} onClick={showProposal}>Propose a new node</button>
          <button className="primary" disabled={!destination || !linkNodeId || busy}
            onClick={() => void linkNode()}>
            {busy ? 'Linking…' : 'Link to this node'}
          </button>
        </div>
      </>}
      </>}
    <button className="icon-button dialog-close" aria-label="Close" onClick={onClose}><Icon name="close"/></button>
  </ModalDialog>;
}
