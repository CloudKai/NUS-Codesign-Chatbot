/** Persistent design canvas: React Flow map, accessible outline and debounced confirmed autosave. */
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  ReactFlow, Background, Controls, ReactFlowProvider, useReactFlow,
  type Edge as FlowEdge,
  type Node as FlowNode,
  type NodeChangeset,
  type EdgeChangeset,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { CanvasDevelopDialog } from './CanvasDevelopDialog';
import { Icon } from './Icon';
import { prefersReducedMotion } from './workspaceLayout';
import { ApiError, currentSession,
  CANVAS_NODE_KINDS, CANVAS_RELATIONS, CANVAS_STAGE_IDS, CANVAS_STAGE_LABELS,
  type Canvas, type CanvasEdge, type CanvasGraph, type CanvasNode, type CanvasNodeKind,
  type CanvasRelation, type CanvasStageId } from './api';
import { readCanvas, readCanvasVersion, readCanvasVersions, restoreCanvasVersion,
  saveCanvas, downloadCanvasExport, readSources, readArtifacts, readArtifact, readCanvases } from './api/client';
import { readDraft, useArtifactAutosave, type AutosaveState } from './useArtifactAutosave';
import { artifactPlainText } from './artifactText';
import type { ArtifactSummaries, CanvasVersion, CanvasVersionSummary, EvidenceReference, Source } from './api';

/** Bounded artifact identity used to expose stale artifact links. */
type ArtifactSummary = ArtifactSummaries['artifacts'][number];

/** Curriculum-facing labels for the supported node categories. */
const NODE_KIND_LABELS: Record<string, string> = {
  note: 'Note', problem: 'Problem', stakeholder: 'Stakeholder', need: 'User need',
  evidence: 'Evidence', assumption: 'Assumption', constraint: 'Constraint', concept: 'Concept',
  specification: 'Specification', ethics: 'Ethics', evaluation: 'Evaluation', reflection: 'Reflection',
};

/** Curriculum-facing labels for the supported relationships. */
const RELATION_LABELS: Record<string, string> = {
  supports: 'supports', addresses: 'addresses', depends_on: 'depends on',
  conflicts_with: 'conflicts with', requires: 'requires', derived_from: 'derived from',
  alternative_to: 'alternative to', evaluated_against: 'evaluated against',
  raises_concern: 'raises concern about',
};

/** Truthful autosave indicator: every state is distinguishable and none claims an unconfirmed save. */
function saveNotice(state: AutosaveState): string {
  if (state === 'saving') return 'Saving…';
  if (state === 'saved') return 'All changes saved.';
  if (state === 'offline') return 'You appear to be offline. Your edits are kept in this tab and save when you continue.';
  if (state === 'failure') return 'Automatic saving failed. Press Save to try again.';
  if (state === 'conflict') return 'This canvas changed in another tab. Resolve the conflict below.';
  return 'Editing — changes save automatically as you write.';
}

/** Stable short identity for a new node or relationship. */
function newId(prefix: string, existing: string[]): string {
  let candidate = '';
  do { candidate = `${prefix}-${Math.random().toString(36).slice(2, 10)}`; } while (existing.includes(candidate));
  return candidate;
}

/** Derive the visual flow nodes from the canonical graph. */
function flowNodes(graph: CanvasGraph, selectedId: string | null,
                   visibleIds: Set<string> | null): FlowNode[] {
  return graph.nodes.map(node => ({
    id: node.id,
    position: { x: node.x, y: node.y },
    data: { label: `${NODE_KIND_LABELS[node.kind] ?? node.kind}: ${node.title}` },
    selected: node.id === selectedId,
    // Filtering dims rather than hides so the map stays honest about what exists.
    className: visibleIds && !visibleIds.has(node.id) ? 'canvas-node-dimmed' : undefined,
  }));
}

function flowEdges(graph: CanvasGraph, visibleIds: Set<string> | null): FlowEdge[] {
  return graph.edges.map(edge => ({
    id: edge.id, source: edge.source, target: edge.target,
    label: RELATION_LABELS[edge.relation] ?? edge.relation, animated: false,
    className: visibleIds && (!visibleIds.has(edge.source) || !visibleIds.has(edge.target))
      ? 'canvas-node-dimmed' : undefined,
  }));
}

/** The stage/category filter result: which node ids stay highlighted. */
function visibleNodeIds(graph: CanvasGraph, kind: string, stage: string): Set<string> | null {
  if (kind === 'all' && stage === 'all') return null;
  return new Set(graph.nodes
    .filter(node => (kind === 'all' || node.kind === kind)
      && (stage === 'all' || node.stage === stage))
    .map(node => node.id));
}

/** Load, autosave and explicitly save one owned canvas; conflicts keep the student's edits. */
function CanvasEditorInner({ owner, threadId, canvasId, expired, onClose, onDiscuss }: {
  owner: string; threadId: string; canvasId: string; expired: () => void; onClose: () => void;
  onDiscuss?: (canvasId: string, revision: number, nodeIds: string[], label: string,
    purpose: 'discuss' | 'draft') => void;
}) {
  const [canvas, setCanvas] = useState<Canvas | null>(null);
  const [graph, setGraph] = useState<CanvasGraph | null>(null);
  const graphRef = useRef<CanvasGraph | null>(null);
  const [title, setTitle] = useState('');
  const titleRef = useRef('');
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [developOpen, setDevelopOpen] = useState(false);
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const [restored, setRestored] = useState(false);
  const [newKind, setNewKind] = useState<CanvasNodeKind>('note');
  const [newTitle, setNewTitle] = useState('');
  const [newDescription, setNewDescription] = useState('');
  const [newStage, setNewStage] = useState('');
  const [newSource, setNewSource] = useState('');
  const [newTarget, setNewTarget] = useState('');
  const [newRelation, setNewRelation] = useState<CanvasRelation>('supports');
  const [newExplanation, setNewExplanation] = useState('');
  const [search, setSearch] = useState('');
  const [kindFilter, setKindFilter] = useState('all');
  const [stageFilter, setStageFilter] = useState('all');
  const [history, setHistory] = useState<CanvasGraph[]>([]);
  const [future, setFuture] = useState<CanvasGraph[]>([]);
  const [sources, setSources] = useState<Source[] | null>(null);
  const [artifactSummaries, setArtifactSummaries] = useState<ArtifactSummary[] | null>(null);
  const [availableCanvases, setAvailableCanvases] = useState<Set<string> | null>(null);
  const [busy, setBusy] = useState(false);
  const [newRefKind, setNewRefKind] = useState<'source' | 'artifact'>('source');
  const [newRefId, setNewRefId] = useState('');
  const [refTarget, setRefTarget] = useState<string | null>(null);
  const [versionsOpen, setVersionsOpen] = useState(false);
  const [versions, setVersions] = useState<CanvasVersionSummary[] | null>(null);
  const [preview, setPreview] = useState<CanvasVersion | null>(null);
  const controller = useRef(new AbortController());
  const active = useRef(true);
  const { fitView } = useReactFlow();
  useEffect(() => {
    active.current = true;
    return () => { active.current = false; controller.current.abort(); };
  }, []);

  async function verify() {
    const session = await currentSession(controller.current.signal);
    if (!active.current) throw new Error('Closed');
    if (session.owner_id !== owner) { expired(); throw new Error('Session changed'); }
  }

  /** Write one new graph snapshot into state and the save-time mirror. */
  function updateGraph(next: CanvasGraph) {
    graphRef.current = next;
    setGraph(next);
  }

  function updateTitle(next: string) {
    titleRef.current = next;
    setTitle(next);
  }

  const autosave = useArtifactAutosave({
    owner,
    artifact: canvas,
    document: () => graphRef.current ?? { nodes: [], edges: [] },
    title: () => titleRef.current,
    enabled: !!canvas,
    draftKind: 'canvas',
    onSave: (savedGraph, savedTitle, revision) => saveCanvas(threadId, canvasId,
      savedGraph as CanvasGraph, revision, savedTitle || null, controller.current.signal),
    getSavedDocument: saved => saved.graph,
    // The confirmed revision reconciles here so the next autosave never goes stale.
    onConfirmed: confirmed => {
      setCanvas(confirmed);
      setHistory([]); setFuture([]); // Durable now: local undo history starts fresh from the saved graph.
    },
    readSaved: async () => {
      const latest = await readCanvas(threadId, canvasId, controller.current.signal);
      await verify();
      return latest;
    },
    onDiscard: latest => {
      updateGraph(latest.graph);
      setCanvas(latest); updateTitle(latest.title);
      setHistory([]); setFuture([]);
      setRestored(false); setStatus('Loaded the saved canvas.');
    },
    onExpired: expired,
  });

  useEffect(() => {
    setCanvas(null); setGraph(null); graphRef.current = null; setError(''); setStatus('');
    setRestored(false); setHistory([]); setFuture([]);
    setStatus('Opening canvas…');
    readCanvas(threadId, canvasId, controller.current.signal)
      .then(async value => {
        await verify();
        if (!active.current) return;
        const draft = readDraft(owner, canvasId, 'canvas');
        const recovered = draft && typeof draft.document === 'object'
          && Array.isArray((draft.document as CanvasGraph).nodes)
          && Array.isArray((draft.document as CanvasGraph).edges) ? draft : null;
        setCanvas(value);
        updateGraph(recovered ? recovered.document as CanvasGraph : value.graph);
        updateTitle(recovered?.title ?? value.title);
        setRestored(!!recovered);
        if (recovered) autosave.restoreDraft(value, recovered);
        setStatus('');
      })
      .catch(error => {
        if (!active.current) return;
        if (error instanceof ApiError && [401, 403].includes(error.status)) { expired(); return; }
        setError('Could not open this canvas. It may have been removed or belongs to another workspace.');
      });
  }, [canvasId, threadId]);

  /** Record one mutating action for local undo and schedule the debounced autosave. */
  function applyChange(mutate: (current: CanvasGraph) => CanvasGraph) {
    const current = graphRef.current;
    if (!current) return;
    const next = mutate(current);
    setHistory(stack => [...stack.slice(-49), current]);
    setFuture([]);
    setStatus('');
    updateGraph(next);
    autosave.markDirty();
  }

  /** Local undo/redo only — durable checkpoints remain the autosaved revisions. */
  function undo() {
    const current = graphRef.current;
    if (!current || !history.length) return;
    const previous = history[history.length - 1];
    setHistory(stack => stack.slice(0, -1));
    setFuture(stack => [current, ...stack].slice(0, 50));
    setStatus('');
    updateGraph(previous);
    autosave.markDirty();
  }

  function redo() {
    const current = graphRef.current;
    if (!current || !future.length) return;
    const next = future[0];
    setFuture(stack => stack.slice(1));
    setHistory(stack => [...stack, current]);
    setStatus('');
    updateGraph(next);
    autosave.markDirty();
  }

  /** One explicit save per action; the confirmed response reconciles without replaying the write. */
  function save() {
    if (!canvas || autosave.state === 'saving') return;
    setError('');
    setStatus('');
    autosave.saveNow();
  }

  /** Download the current saved canvas in one of the three reviewed formats. */
  async function download(format: 'json' | 'outline' | 'svg') {
    if (!canvas || autosave.state === 'saving') return;
    setError('');
    try {
      await verify();
      await downloadCanvasExport(threadId, canvasId, format, title || 'canvas',
        controller.current.signal);
      await verify();
      if (active.current) setStatus(`Exported as ${format}.`);
    } catch (error) {
      if (error instanceof ApiError && [401, 403].includes(error.status)) { expired(); return; }
      if (active.current) setError('Could not export this canvas. Try again.');
    }
  }

  /** Load the bounded version history when the panel opens; versions are metadata only. */
  function toggleHistory() {
    const opening = !versionsOpen;
    setVersionsOpen(opening);
    setPreview(null);
    if (opening && versions === null) {
      readCanvasVersions(threadId, canvasId, controller.current.signal)
        .then(list => { if (active.current) setVersions(list.versions); })
        .catch(error => {
          if (error instanceof ApiError && [401, 403].includes(error.status)) { expired(); return; }
          if (active.current) setError('Could not load version history. Try again.');
        });
    }
  }

  async function openPreview(revision: number) {
    try {
      const value = await readCanvasVersion(threadId, canvasId, revision, controller.current.signal);
      await verify();
      if (active.current) setPreview(value);
    } catch (error) {
      if (error instanceof ApiError && [401, 403].includes(error.status)) { expired(); return; }
      if (active.current) setError('Could not open that version. Try again.');
    }
  }

  /** Restore as a new revision guarded by the current one; intermediates stay in history. */
  async function restore(revision: number) {
    if (!canvas || autosave.state === 'saving' || conflict) return;
    setError('');
    try {
      const started = await autosave.applyExternalWrite(async saved => {
        await verify();
        const restored = await restoreCanvasVersion(threadId, canvasId, revision,
          saved.revision, controller.current.signal);
        await verify();
        return restored;
      }, confirmed => {
        updateGraph(confirmed.graph);
        setCanvas(confirmed); updateTitle(confirmed.title);
        setHistory([]); setFuture([]); setPreview(null);
        setVersions(null); // The next History open lists the restore checkpoint too.
        setStatus(`Restored version ${revision} as the current snapshot.`);
      });
      if (!started) setError('Save or resolve your canvas edits before restoring an earlier version.');
    } catch (error) {
      if (error instanceof ApiError && [401, 403].includes(error.status)) { expired(); return; }
      if (error instanceof ApiError && error.status === 409) {
        if (active.current) setError('This canvas changed while restoring. Reload it before trying again.');
        return;
      }
      if (active.current) setError('Could not restore that version. Try again.');
    }
  }

  async function resolveConflict(resolve: () => Promise<void>) {
    setError(''); setStatus('');
    try { await resolve(); }
    catch { if (active.current) setError('Could not resolve the conflict. Try again.'); }
  }

  /** Add one node from the outline form at a free position near the origin. */
  function addNode() {
    if (!newTitle.trim()) return;
    const current = graphRef.current;
    if (!current) return;
    const offset = current.nodes.length * 24;
    const node: CanvasNode = {
      id: newId('n', current.nodes.map(entry => entry.id)),
      kind: newKind,
      title: newTitle.trim().slice(0, 200),
      description: newDescription.trim().slice(0, 2000),
      x: 60 + offset, y: 60 + offset,
      ...(newStage ? { stage: newStage as CanvasStageId } : {}),
    };
    applyChange(currentNode => ({ ...currentNode, nodes: [...currentNode.nodes, node] }));
    setNewTitle(''); setNewDescription(''); setNewStage('');
  }

  /** Duplicate one node with its content; the copy sits beside the original. */
  function duplicateNode(id: string) {
    const current = graphRef.current;
    if (!current) return;
    const node = current.nodes.find(entry => entry.id === id);
    if (!node) return;
    const copy: CanvasNode = { ...node, id: newId('n', current.nodes.map(entry => entry.id)),
      x: node.x + 32, y: node.y + 32 };
    applyChange(currentNode => ({ ...currentNode, nodes: [...currentNode.nodes, copy] }));
  }

  /** Update one node's outline fields. */
  function updateNode(id: string, patch: Partial<CanvasNode>) {
    applyChange(current => ({
      ...current, nodes: current.nodes.map(node => node.id === id ? { ...node, ...patch } : node) }));
  }

  /** Load the notebook's sources once so the evidence picker and availability are honest. */
  useEffect(() => {
    if (!canvas || sources !== null || !refTarget) return;
    readSources(threadId, controller.current.signal)
      .then(list => { if (active.current) setSources(list.sources); })
      .catch(error => {
        if (error instanceof ApiError && [401, 403].includes(error.status)) { expired(); return; }
        if (active.current) setError('Could not load sources for the evidence picker. Try again.');
      });
  }, [canvas, sources, refTarget]);

  /** Attach one evidence reference to a node; the server re-validates every save. */
  function addReference(nodeId: string) {
    const current = graphRef.current;
    if (!current || !newRefId.trim()) return;
    const node = current.nodes.find(entry => entry.id === nodeId);
    if (!node) return;
    const reference: EvidenceReference = newRefKind === 'source'
      ? { kind: 'source', id: newRefId.trim() }
      : { kind: 'artifact', id: newRefId.trim() };
    const references = [...(node.references ?? []).map(entry => ({ ...entry })), reference];
    applyChange(currentGraph => ({
      ...currentGraph,
      nodes: currentGraph.nodes.map(entry => entry.id === nodeId ? { ...entry, references } : entry),
    }));
    setNewRefId('');
  }

  /** Detach one evidence reference from a node. */
  function removeReference(nodeId: string, index: number) {
    const current = graphRef.current;
    if (!current) return;
    const node = current.nodes.find(entry => entry.id === nodeId);
    if (!node?.references) return;
    const references = node.references.filter((_entry, position) => position !== index);
    applyChange(currentGraph => ({
      ...currentGraph,
      nodes: currentGraph.nodes.map(entry => entry.id === nodeId
        ? { ...entry, references: references.length ? references : undefined } : entry),
    }));
  }

  /** A source reference is available while its id is still in the notebook's source list. */
  function referenceState(node: CanvasNode, reference: EvidenceReference): string {
    void node;
    if (reference.kind === 'source') {
      const available = sources?.some(source => source.id === reference.id);
      if (available === false) return 'Unavailable or outdated';
    }
    if (reference.kind === 'canvas_node' && reference.canvas_id && availableCanvases
      && !availableCanvases.has(reference.canvas_id)) return 'Unavailable canvas node';
    const kindLabels: Record<string, string> = { source: 'Source', message: 'Message',
      artifact: 'Artifact', canvas_node: 'Canvas node' };
    if (reference.kind === 'artifact') {
      const summary = artifactSummaries?.find(entry => entry.id === reference.id);
      const label = summary?.title ?? reference.id.slice(0, 18);
      return typeof reference.revision === 'number'
        ? `${summary?.title ?? 'Document'} (linked saved version ${reference.revision})`
        : `${kindLabels[reference.kind]}: ${label}`;
    }
    return `${kindLabels[reference.kind] ?? reference.kind}: ${reference.id.slice(0, 18)}`;
  }

  /** An artifact link is stale when the saved document has moved past the linked revision. */
  function staleArtifactSummary(reference: EvidenceReference): ArtifactSummary | null {
    if (reference.kind !== 'artifact' || typeof reference.revision !== 'number') return null;
    const summary = artifactSummaries?.find(entry => entry.id === reference.id);
    return summary && summary.revision > reference.revision ? summary : null;
  }

  /** Load the notebook's bounded artifact list once a node links a document. */
  useEffect(() => {
    if (artifactSummaries !== null) return;
    const hasArtifactLinks = (graphRef.current?.nodes ?? []).some(
      node => node.references?.some(reference => reference.kind === 'artifact'));
    if (!hasArtifactLinks) return;
    readArtifacts(threadId, controller.current.signal)
      .then(list => { if (active.current) setArtifactSummaries(list.artifacts); })
      .catch(() => { if (active.current) setArtifactSummaries([]); });
  }, [graph, artifactSummaries, threadId]);

  const hasCanvasReferences = graph?.nodes.some(node => node.references?.some(ref => ref.kind === 'canvas_node'));
  useEffect(() => {
    if (!hasCanvasReferences) return;
    const request = new AbortController();
    readCanvases(threadId, request.signal)
      .then(list => {
        if (!request.signal.aborted && list.owner_id === owner) {
          setAvailableCanvases(new Set(list.canvases.map(canvas => canvas.id)));
        }
      })
      .catch(() => { /* Keep the link visible when availability could not be checked. */ });
    return () => request.abort();
  }, [hasCanvasReferences, owner, threadId]);

  /** Explicit stale-link update: refresh this node from the document's current saved text.
   * Nothing syncs automatically — the student reviews the change in the outline before saving.
   */
  async function updateFromArtifact(nodeId: string, reference: EvidenceReference) {
    if (busy) return;
    setBusy(true); setError('');
    try {
      const artifact = await readArtifact(threadId, reference.id, controller.current.signal);
      if (!active.current) return;
      applyChange(current => ({
        ...current,
        nodes: current.nodes.map(node => node.id === nodeId ? {
          ...node,
          description: artifactPlainText(artifact.document).slice(0, 2000),
          references: (node.references ?? []).map(entry =>
            entry.kind === 'artifact' && entry.id === artifact.id
              ? { ...entry, revision: artifact.revision } : { ...entry }),
        } : node),
      }));
      setStatus(`Node refreshed from “${artifact.title}”. Review it, then save.`);
    } catch (caught) {
      if (caught instanceof ApiError && [401, 403].includes(caught.status)) { expired(); return; }
      if (caught instanceof ApiError && caught.status === 404) {
        setError('That document is no longer available. Keep this node as it is or detach the link.');
        return;
      }
      setError('Could not read that document. Your node is unchanged.');
    } finally { if (active.current) setBusy(false); }
  }

  /** Remove nodes and their incident relationships. */
  function removeNodes(ids: string[]) {
    const current = graphRef.current;
    if (!current) return;
    const dropping = new Set(ids);
    applyChange(node => ({
      nodes: node.nodes.filter(entry => !dropping.has(entry.id)),
      edges: node.edges.filter(edge => !dropping.has(edge.source) && !dropping.has(edge.target)),
    }));
    if (selectedId && dropping.has(selectedId)) setSelectedId(null);
  }

  /** Add one labeled relationship between two existing nodes. */
  function connect() {
    const current = graphRef.current;
    if (!current || !newSource || !newTarget || newSource === newTarget) return;
    if (current.edges.some(edge => edge.source === newSource && edge.target === newTarget)) {
      setError('Those nodes are already connected.');
      return;
    }
    const edge: CanvasEdge = {
      id: newId('e', current.edges.map(entry => entry.id)),
      source: newSource, target: newTarget, relation: newRelation,
      explanation: newExplanation.trim().slice(0, 2000),
    };
    applyChange(node => ({ ...node, edges: [...node.edges, edge] }));
    setNewSource(''); setNewTarget(''); setNewExplanation('');
    setError('');
  }

  /** Update one relationship's outline fields. */
  function updateEdge(id: string, patch: Partial<CanvasEdge>) {
    applyChange(current => ({
      ...current, edges: current.edges.map(edge => edge.id === id ? { ...edge, ...patch } : edge) }));
  }

  /** Remove one or more relationships. */
  function removeEdges(ids: string[]) {
    const current = graphRef.current;
    if (!current) return;
    const dropping = new Set(ids);
    applyChange(node => ({
      ...node, edges: node.edges.filter(edge => !dropping.has(edge.id)) }));
  }

  /** Dragging a visual node updates the snapshot; one debounced save covers the whole move. */
  const onNodesChange = useCallback((changes: NodeChangeset<FlowNode>) => {
    const moved = changes.getByType('position').filter(change => change.position);
    const removed = changes.getByType('remove').map(change => change.id);
    if (removed.length) { removeNodes(removed); return; }
    const current = graphRef.current;
    if (!moved.length || !current) return;
    const positions = new Map(moved.map(change => [change.id, change.position as { x: number; y: number }]));
    updateGraph({
      ...current,
      nodes: current.nodes.map(node => positions.has(node.id)
        ? { ...node, x: positions.get(node.id)!.x, y: positions.get(node.id)!.y } : node),
    });
    // One autosave checkpoint per completed drag, never per pointer movement.
    if (moved.some(change => change.dragging === false)) {
      setHistory(stack => [...stack.slice(-49), current]);
      setFuture([]);
      setStatus('');
      autosave.markDirty();
    }
  }, [autosave]);

  /** Canvas-side edge deletion joins the same graph state and autosave cycle. */
  const onEdgesChange = (changes: EdgeChangeset) => {
    const removed = changes.getByType('remove').map(change => change.id);
    if (removed.length) removeEdges(removed);
  };

  /** Keyboard undo/redo outside text fields; durable history remains the saved revisions. */
  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== 'z') return;
      const target = event.target as HTMLElement | null;
      if (target && ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)) return;
      event.preventDefault();
      if (event.shiftKey) redo(); else undo();
    };
    window.addEventListener('keydown', shortcut);
    return () => window.removeEventListener('keydown', shortcut);
  });

  /** Search narrows the outline and dims non-matching nodes; locate centers the match. */
  const query = search.trim().toLowerCase();
  const matches = graph && query
    ? graph.nodes.filter(node => node.title.toLowerCase().includes(query)
      || node.description.toLowerCase().includes(query))
    : null;
  const filteredIds = graph ? visibleNodeIds(graph, kindFilter, stageFilter) : null;
  const outlineNodes = graph?.nodes.filter(node =>
    (!matches || matches.some(match => match.id === node.id))
    && (!filteredIds || filteredIds.has(node.id))) ?? [];

  const nodeById = (id: string) => graph?.nodes.find(node => node.id === id);
  const conflict = autosave.state === 'conflict';

  return <section className="canvas-editor" aria-label="Design canvas">
    <header className="artifact-header">
      <button className="icon-button" aria-label="Back to notebook" onClick={onClose}><Icon name="close"/></button>
      <input className="artifact-title" aria-label="Canvas title" maxLength={200} value={title}
        disabled={conflict || !canvas}
        onChange={event => { setStatus(''); updateTitle(event.target.value); autosave.markDirty(); }}/>
      <button aria-label="Undo last local edit" title="Undo (local only)" disabled={!history.length || conflict}
        onClick={undo}><Icon name="refresh"/></button>
      <button aria-label="Redo last local edit" title="Redo (local only)" disabled={!future.length || conflict}
        onClick={redo}><Icon name="refresh"/></button>
      <button aria-expanded={versionsOpen} aria-controls="canvas-history" onClick={toggleHistory}
        disabled={!canvas}>
        <Icon name="search"/> History
      </button>
      <button className="primary" disabled={conflict || !canvas || autosave.state === 'saving'} onClick={save}>
        {autosave.state === 'saving' ? 'Saving…' : 'Save'}
      </button>
      {onDiscuss ? <button aria-label="Ask the coach about the selected node" title="Ask the coach about the selected node"
        disabled={!selectedId || conflict} onClick={() => {
        const node = graph?.nodes.find(entry => entry.id === selectedId);
        if (node && canvas) onDiscuss(canvas.id, canvas.revision, [node.id], node.title, 'discuss');
      }}>Ask the coach</button> : null}
      {canvas && graph?.nodes.length ? <button aria-label="Develop canvas nodes into an artifact"
        title="Develop selected canvas nodes into an artifact" disabled={conflict}
        onClick={() => setDevelopOpen(true)}>Develop into artifact</button> : null}
    </header>
    {error ? <p role="alert">{error}</p> : null}
    {restored ? <p role="status">Restored your unsaved edits from this browser.</p> : null}
    <p role="status">{conflict ? saveNotice(autosave.state) : status || saveNotice(autosave.state)}</p>
    {conflict ? <div role="alert" className="artifact-conflict">
      <p>Your edits in this tab were not saved because the canvas changed elsewhere. Your version is still shown.</p>
      <button onClick={() => void resolveConflict(autosave.resolveByReload)}>Reload the saved canvas</button>
      <button onClick={() => void resolveConflict(autosave.resolveByKeep)}>Keep my edits and save over</button>
    </div> : null}
    {canvas ? <div className="artifact-export" role="group" aria-label="Export canvas">
      <button disabled={conflict || autosave.state === 'saving'} onClick={() => void download('json')}>Export JSON</button>
      <button disabled={conflict || autosave.state === 'saving'} onClick={() => void download('outline')}>Export outline</button>
      <button disabled={conflict || autosave.state === 'saving'} onClick={() => void download('svg')}>Export SVG</button>
    </div> : null}
    {canvas && versionsOpen ? <section className="artifact-history" id="canvas-history" aria-label="Canvas version history">
      <h3>Canvas version history</h3>
      {versions === null ? <p role="status" className="supporting">Checking versions…</p> : versions.length
        ? <ul>{versions.map(entry => <li key={entry.revision}>
            <button aria-pressed={preview?.revision === entry.revision} disabled={conflict}
              onClick={() => void openPreview(entry.revision)}>
              Version {entry.revision} ·{' '}
              {entry.origin === 'restore' ? `restored from ${entry.restored_from}` : 'saved'} ·{' '}
              {new Date(entry.created_at).toLocaleString()}
            </button>
          </li>)}</ul>
        : <p className="supporting">No earlier versions yet.</p>}
      {preview ? <div className="artifact-version-preview">
        <p className="supporting">Previewing version {preview.revision} — nothing changes until you restore.</p>
        <pre>{versionOutline(preview)}</pre>
        <button disabled={conflict || autosave.state === 'saving'} onClick={() => void restore(preview.revision)}>
          Restore version {preview.revision}
        </button>
        <button onClick={() => setPreview(null)}>Close preview</button>
      </div> : null}
    </section> : null}
    {canvas && graph ? <>
      <div className="canvas-controls" role="group" aria-label="Find and filter nodes">
        <label htmlFor="canvas-search">Search nodes</label>
        <input id="canvas-search" value={search} placeholder="Find a node…"
          onChange={event => setSearch(event.target.value)}/>
        {matches && matches.length === 1
          ? <button onClick={() => { setSelectedId(matches[0].id);
              // The CSS layer cannot suppress this JS-driven zoom, so the OS
              // reduced-motion preference chooses an instant move here.
              void fitView({ nodes: [{ id: matches[0].id }], duration: prefersReducedMotion() ? 0 : 300 }); }}>
              Locate “{matches[0].title.slice(0, 30)}”</button>
          : null}
        <label htmlFor="canvas-kind-filter">Type</label>
        <select id="canvas-kind-filter" value={kindFilter}
          onChange={event => setKindFilter(event.target.value)}>
          <option value="all">All types</option>
          {CANVAS_NODE_KINDS.map(kind => <option key={kind} value={kind}>{NODE_KIND_LABELS[kind]}</option>)}
        </select>
        <label htmlFor="canvas-stage-filter">Stage</label>
        <select id="canvas-stage-filter" value={stageFilter}
          onChange={event => setStageFilter(event.target.value)}>
          <option value="all">All stages</option>
          {CANVAS_STAGE_IDS.map(stage => <option key={stage} value={stage}>{CANVAS_STAGE_LABELS[stage]}</option>)}
        </select>
      </div>
      <div className="canvas-surface" aria-label="Canvas map">
        <ReactFlow nodes={flowNodes(graph, selectedId, filteredIds)} edges={flowEdges(graph, filteredIds)}
          onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
          onNodeClick={(_event, node) => setSelectedId(node.id)}
          onPaneClick={() => setSelectedId(null)}
          fitView proOptions={{ hideAttribution: false }}>
          <Background/>
          <Controls showInteractive={false}/>
        </ReactFlow>
      </div>
      <section className="canvas-outline" aria-label="Canvas outline">
        <h3>Outline</h3>
        <p className="supporting">Every map action works from this list without dragging. Undo and redo are local to this tab until the next save.</p>
        <form className="canvas-add-node" onSubmit={event => { event.preventDefault(); addNode(); }}>
          <h4>Add a node</h4>
          <label htmlFor="canvas-node-kind">Node type</label>
          <select id="canvas-node-kind" value={newKind} onChange={event => setNewKind(event.target.value as CanvasNodeKind)}>
            {CANVAS_NODE_KINDS.map(kind => <option key={kind} value={kind}>{NODE_KIND_LABELS[kind]}</option>)}
          </select>
          <label htmlFor="canvas-node-title">Title</label>
          <input id="canvas-node-title" maxLength={200} value={newTitle} placeholder="e.g. Students cross unsafely"
            onChange={event => setNewTitle(event.target.value)}/>
          <label htmlFor="canvas-node-description">Description (optional)</label>
          <input id="canvas-node-description" maxLength={2000} value={newDescription}
            onChange={event => setNewDescription(event.target.value)}/>
          <label htmlFor="canvas-node-stage">Thinking Path stage (optional label)</label>
          <select id="canvas-node-stage" value={newStage} onChange={event => setNewStage(event.target.value)}>
            <option value="">No stage</option>
            {CANVAS_STAGE_IDS.map(stage => <option key={stage} value={stage}>{CANVAS_STAGE_LABELS[stage]}</option>)}
          </select>
          <button type="submit" disabled={!newTitle.trim()}>Add node</button>
        </form>
        {outlineNodes.length ? <ul className="canvas-node-list" aria-label="Node list">
          {outlineNodes.map(node => <li key={node.id}>
            <details open={node.id === selectedId}>
              <summary>{NODE_KIND_LABELS[node.kind] ?? node.kind}: {node.title}
                {node.stage ? <span className="supporting"> · {CANVAS_STAGE_LABELS[node.stage]}</span> : null}</summary>
              <label htmlFor={`canvas-kind-${node.id}`}>Type</label>
              <select id={`canvas-kind-${node.id}`} value={node.kind}
                onChange={event => updateNode(node.id, { kind: event.target.value as CanvasNodeKind })}>
                {CANVAS_NODE_KINDS.map(kind => <option key={kind} value={kind}>{NODE_KIND_LABELS[kind]}</option>)}
              </select>
              <label htmlFor={`canvas-title-${node.id}`}>Title</label>
              <input id={`canvas-title-${node.id}`} maxLength={200} value={node.title}
                onChange={event => updateNode(node.id, { title: event.target.value })}/>
              <label htmlFor={`canvas-description-${node.id}`}>Description</label>
              <input id={`canvas-description-${node.id}`} maxLength={2000} value={node.description}
                onChange={event => updateNode(node.id, { description: event.target.value })}/>
              <label htmlFor={`canvas-stage-${node.id}`}>Thinking Path stage (optional label)</label>
              <select id={`canvas-stage-${node.id}`} value={node.stage ?? ''}
                onChange={event => updateNode(node.id,
                  event.target.value ? { stage: event.target.value as CanvasStageId } : { stage: undefined })}>
                <option value="">No stage</option>
                {CANVAS_STAGE_IDS.map(stage => <option key={stage} value={stage}>{CANVAS_STAGE_LABELS[stage]}</option>)}
              </select>
              <button onClick={() => duplicateNode(node.id)}>Duplicate node</button>
              <button className="danger-action" onClick={() => removeNodes([node.id])}>
                Remove node and its connections
              </button>
              <div className="canvas-references">
                <h5>Evidence</h5>
                {node.references?.length
                  ? <ul>{node.references.map((reference, index) => {
                      const stale = staleArtifactSummary(reference);
                      return <li key={`${reference.kind}-${reference.id}`}>
                      <span>{referenceState(node, reference)}{stale
                        ? ' — the document has newer saved changes'
                        : ''}</span>
                      {stale ? <button disabled={busy}
                        onClick={() => void updateFromArtifact(node.id, reference)}>
                        Update from artifact
                      </button> : null}
                      <button onClick={() => removeReference(node.id, index)}>Detach</button>
                    </li>; })}
                  </ul>
                  : <p className="supporting">No evidence linked yet.</p>}
                {refTarget === node.id ? <>
                  <label htmlFor={`canvas-ref-kind-${node.id}`}>Evidence type</label>
                  <select id={`canvas-ref-kind-${node.id}`} value={newRefKind}
                    onChange={event => setNewRefKind(event.target.value as 'source' | 'artifact')}>
                    <option value="source">Source (course or upload)</option>
                    <option value="artifact">Another document</option>
                  </select>
                  {newRefKind === 'source' && sources
                    ? <label htmlFor={`canvas-ref-id-${node.id}`}>Source</label>
                    : <label htmlFor={`canvas-ref-id-${node.id}`}>Evidence id</label>}
                  {newRefKind === 'source' && sources
                    ? <select id={`canvas-ref-id-${node.id}`} value={newRefId}
                        onChange={event => setNewRefId(event.target.value)}>
                        <option value="">Choose a source…</option>
                        {sources.map(source => <option key={source.id} value={source.id}>{source.title}</option>)}
                      </select>
                    : <input id={`canvas-ref-id-${node.id}`} value={newRefId} maxLength={128}
                        placeholder="Paste the evidence id" onChange={event => setNewRefId(event.target.value)}/>}
                  <button disabled={!newRefId.trim()} onClick={() => addReference(node.id)}>Link evidence</button>
                  <button onClick={() => setRefTarget(null)}>Done</button>
                </> : <button onClick={() => setRefTarget(node.id)}>Link evidence…</button>}
              </div>
            </details>
          </li>)}
        </ul> : <p className="supporting">{query || kindFilter !== 'all' || stageFilter !== 'all'
          ? 'No nodes match the current search or filter.'
          : 'No nodes yet. Add your first idea above.'}</p>}
        <form className="canvas-connect" onSubmit={event => { event.preventDefault(); connect(); }}>
          <h4>Connect two nodes</h4>
          <label htmlFor="canvas-edge-source">From</label>
          <select id="canvas-edge-source" value={newSource} onChange={event => setNewSource(event.target.value)}>
            <option value="">Choose a node…</option>
            {graph.nodes.map(node => <option key={node.id} value={node.id}>{node.title}</option>)}
          </select>
          <label htmlFor="canvas-edge-relation">Relationship</label>
          <select id="canvas-edge-relation" value={newRelation}
            onChange={event => setNewRelation(event.target.value as CanvasRelation)}>
            {CANVAS_RELATIONS.map(relation => <option key={relation} value={relation}>{RELATION_LABELS[relation]}</option>)}
          </select>
          <label htmlFor="canvas-edge-target">To</label>
          <select id="canvas-edge-target" value={newTarget} onChange={event => setNewTarget(event.target.value)}>
            <option value="">Choose a node…</option>
            {graph.nodes.map(node => <option key={node.id} value={node.id}>{node.title}</option>)}
          </select>
          <label htmlFor="canvas-edge-explanation">Why (optional)</label>
          <input id="canvas-edge-explanation" maxLength={2000} value={newExplanation}
            onChange={event => setNewExplanation(event.target.value)}/>
          <button type="submit" disabled={!newSource || !newTarget || newSource === newTarget}>Connect</button>
        </form>
        {graph.edges.length ? <ul className="canvas-edge-list" aria-label="Connection list">
          {graph.edges.map(edge => <li key={edge.id}>
            <details>
              <summary>{nodeById(edge.source)?.title ?? edge.source} — {RELATION_LABELS[edge.relation]} — {nodeById(edge.target)?.title ?? edge.target}</summary>
              <label htmlFor={`canvas-relation-${edge.id}`}>Relationship</label>
              <select id={`canvas-relation-${edge.id}`} value={edge.relation}
                onChange={event => updateEdge(edge.id, { relation: event.target.value as CanvasRelation })}>
                {CANVAS_RELATIONS.map(relation => <option key={relation} value={relation}>{RELATION_LABELS[relation]}</option>)}
              </select>
              <label htmlFor={`canvas-explanation-${edge.id}`}>Why</label>
              <input id={`canvas-explanation-${edge.id}`} maxLength={2000} value={edge.explanation}
                onChange={event => updateEdge(edge.id, { explanation: event.target.value })}/>
              <button className="danger-action" onClick={() => removeEdges([edge.id])}>Remove connection</button>
            </details>
          </li>)}
        </ul> : <p className="supporting">No connections yet. Link two nodes to explain how they relate.</p>}
      </section>
    </> : null}
    {developOpen && canvas ? <CanvasDevelopDialog threadId={threadId} canvas={canvas}
      initialNodeIds={selectedId ? [selectedId] : []}
      onClose={() => setDevelopOpen(false)}
      onDiscuss={onDiscuss}/> : null}
  </section>;
}

/** Bounded plain-text projection of one version's graph for the readable preview. */
function versionOutline(version: CanvasVersion): string {
  const lines = version.graph.nodes.map(node =>
    `${NODE_KIND_LABELS[node.kind] ?? node.kind}: ${node.title}`
      + (node.stage ? ` · ${CANVAS_STAGE_LABELS[node.stage]}` : ''));
  const byId = new Map(version.graph.nodes.map(node => [node.id, node.title]));
  for (const edge of version.graph.edges) {
    lines.push(`${byId.get(edge.source) ?? edge.source} — ${RELATION_LABELS[edge.relation] ?? edge.relation} — ${byId.get(edge.target) ?? edge.target}`);
  }
  return lines.join('\n') || '(empty canvas)';
}

/** The provider powers locate/fit-view from the outline controls. */
export function CanvasEditor({ owner, threadId, canvasId, expired, onClose, onDiscuss }: {
  owner: string; threadId: string; canvasId: string; expired: () => void; onClose: () => void;
  onDiscuss?: (canvasId: string, revision: number, nodeIds: string[], label: string,
    purpose: 'discuss' | 'draft') => void;
}) {
  return <ReactFlowProvider>
    <CanvasEditorInner key={JSON.stringify([owner, threadId, canvasId])} owner={owner} threadId={threadId} canvasId={canvasId}
      expired={expired} onClose={onClose} onDiscuss={onDiscuss}/>
  </ReactFlowProvider>;
}
