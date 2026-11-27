/** Develop selected canvas nodes into an artifact: manual assembly or an explicit
 * coach synthesis request. Nothing is created until the student confirms, and
 * confirmation always creates a new artifact — an existing one is never
 * overwritten automatically.
 */
import { useEffect, useRef, useState } from 'react';
import { Icon } from './Icon';
import { ARTIFACT_KINDS, ApiError, type ArtifactDocument, type Canvas,
  type EvidenceReference } from './api';
import { createArtifact } from './api/client';
import { ModalDialog } from './ModalDialog';

const KIND_LABELS: Record<string, string> = {
  note: 'Note', problem: 'Problem', stakeholder: 'Stakeholder', need: 'User need',
  evidence: 'Evidence', assumption: 'Assumption', constraint: 'Constraint', concept: 'Concept',
  specification: 'Specification', ethics: 'Ethics', evaluation: 'Evaluation', reflection: 'Reflection',
};
const ARTIFACT_LABELS: Record<string, string> = {
  notes: 'General notes', problem_identification: 'Problem identification',
  concept_generation: 'Concept generation', design_specification: 'Design specification',
  ethics_critical_thinking: 'Ethics & critical thinking', reflection: 'Reflection',
};

/** One retry-safe create key for this mounted dialog; never regenerated on retry. */
function newRequestId(): string {
  const uuid = globalThis.crypto?.randomUUID?.();
  const suffix = uuid ?? `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  return `develop:${suffix}`;
}

function documentFromNodes(canvas: Canvas, nodeIds: string[]): ArtifactDocument {
  const lines = canvas.graph.nodes
    .filter(node => nodeIds.includes(node.id))
    .map(node => {
      const kind = KIND_LABELS[node.kind] ?? node.kind;
      return node.description.trim()
        ? `${kind}: ${node.title} — ${node.description.trim()}`
        : `${kind}: ${node.title}`;
    });
  return { type: 'doc', content: lines.length
    ? lines.map(line => ({ type: 'paragraph', content: [{ type: 'text', text: line }] }))
    : [{ type: 'paragraph', content: [{ type: 'text', text: '(no nodes selected)' }] }] };
}

/** Choose canvas nodes and develop them into a reviewed artifact draft. */
export function CanvasDevelopDialog({ threadId, canvas, initialNodeIds, onClose, onDone, onDiscuss }: {
  threadId: string; canvas: Canvas; initialNodeIds: string[];
  onClose: () => void;
  onDone?: (artifactId: string) => void;
  onDiscuss?: (canvasId: string, revision: number, nodeIds: string[], label: string,
    purpose: 'discuss' | 'draft') => void;
}) {
  const [selected, setSelected] = useState<string[]>(() =>
    canvas.graph.nodes
      .filter(node => initialNodeIds.includes(node.id))
      .map(node => node.id));
  const [kind, setKind] = useState<string>('notes');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState<string | null>(null);
  const [requestId] = useState(newRequestId);
  const [frozen, setFrozen] = useState(false);
  const controller = useRef(new AbortController());
  useEffect(() => () => controller.current.abort(), []);

  /** Manual assembly is the student's own composition over saved node text. */
  async function assemble() {
    if (!selected.length || busy) return;
    setBusy(true); setError('');
    try {
      const title = `From ${canvas.title}`.slice(0, 200);
      // Provenance: contributing nodes plus the canvas revision they came from.
      const references: EvidenceReference[] = selected.map(nodeId => ({
        kind: 'canvas_node' as const, id: nodeId, canvas_id: canvas.id,
        revision: canvas.revision }));
      const created = await createArtifact(threadId, title,
        documentFromNodes(canvas, selected), controller.current.signal, kind, references,
        requestId);
      setCreated(created.id);
      onDone?.(created.id);
    } catch (caught) {
      if (caught instanceof ApiError && [401, 403].includes(caught.status)) { onClose(); return; }
      if (caught instanceof ApiError && caught.status === 422) {
        setError('This selection could not be created. An earlier attempt may already have saved it — check your documents before trying again.');
        return;
      }
      // The create may have committed even though the acknowledgement was
      // lost. One request id makes a retry replay safely, so the payload is
      // frozen: a retry is provably the same request.
      setFrozen(true);
      setError("We couldn't confirm whether the artifact was created. Check your documents before trying again; a retry is safe and will not duplicate it.");
    } finally { setBusy(false); }
  }

  function requestDraft() {
    if (!selected.length || !onDiscuss) return;
    onDiscuss(canvas.id, canvas.revision, selected, 'draft synthesis', 'draft');
  }

  return <ModalDialog label="Develop canvas nodes into an artifact" onClose={onClose}>
    <h2>Develop into an artifact</h2>
    {created ? <p role="status" className="supporting">Artifact created. Open it from your notebook to continue editing — this canvas is unchanged.</p> : null}
    {error ? <p role="alert">{error}</p> : null}
    <fieldset className="develop-nodes">
      <legend>Contributing nodes</legend>
      {canvas.graph.nodes.length
        ? canvas.graph.nodes.map(node => <label key={node.id} className="develop-node">
            <input type="checkbox" checked={selected.includes(node.id)} disabled={frozen}
              onChange={event => setSelected(current => event.target.checked
                ? [...current, node.id]
                : current.filter(id => id !== node.id))}/>
            <span>{KIND_LABELS[node.kind] ?? node.kind}: {node.title}</span>
          </label>)
        : <p className="supporting">This canvas has no nodes yet.</p>}
    </fieldset>
    <label htmlFor="develop-kind">Artifact type</label>
    <select id="develop-kind" value={kind} disabled={frozen}
      onChange={event => setKind(event.target.value)}>
      {ARTIFACT_KINDS.map(option => <option key={option} value={option}>{ARTIFACT_LABELS[option]}</option>)}
    </select>
    <p className="supporting">Assembling creates a new artifact from the checked nodes' saved text — it never changes an existing artifact or this canvas. Drafting asks the coach to synthesize the checked nodes into a draft you review before anything is created.</p>
    <div className="entry-actions">
      <button className="primary" disabled={!selected.length || busy} onClick={() => void assemble()}>
        {busy ? 'Assembling…' : 'Assemble myself'}</button>
      {onDiscuss ? <button disabled={!selected.length} onClick={requestDraft}>
        Draft with the coach</button> : null}
      <button onClick={onClose}>Close</button>
    </div>
    <button className="icon-button dialog-close" aria-label="Close" onClick={onClose}><Icon name="close"/></button>
  </ModalDialog>;
}
