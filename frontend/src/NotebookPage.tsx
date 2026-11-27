/** Folder landing page for chats, persistent documents, canvases and the notebook's reusable evidence. */
import { useEffect, useRef, useState } from 'react';
import { currentSession } from './api';
import type { CanvasSummaries, ChatSummary, Notebook } from './api';
import { createCanvas, deleteArtifact, deleteCanvas, duplicateArtifact, downloadProjectExport, readArtifacts, readCanvases } from './api/client';
import { ApiError } from './api/errors';
import { Icon } from './Icon';
import { relativeTime } from './HomeView';
import { originalNotebookChat, recentChats } from './notebookChats';
import { Sources } from './Sources';

interface NotebookPageProps {
  notebook: Notebook;
  entries: Notebook[];
  summaries: Record<string, ChatSummary>;
  owner: string;
  locked: boolean;
  expired: () => void;
  createChat: () => void;
  openChat: (id: string) => void;
  openArtifact: (artifactId: string) => void;
  createArtifact: (title: string, kind: string) => Promise<{ id: string }>;
  openCanvas: (canvasId: string) => void;
}

const views = ['Chats', 'Documents', 'Canvas', 'Sources', 'Export'] as const;

/** Curriculum-facing labels for the supported artifact types. */
const KIND_LABELS: Record<string, string> = {
  notes: 'General notes',
  problem_identification: 'Problem identification',
  concept_generation: 'Concept generation',
  design_specification: 'Design specification',
  ethics_critical_thinking: 'Ethics & critical thinking',
  reflection: 'Reflection',
};

/** Render the notebook conversation list, persistent documents and the source manager. */
export function NotebookPage({ notebook, entries, summaries, owner, locked, expired, createChat, openChat, openArtifact, createArtifact, openCanvas }: NotebookPageProps) {
  const [tab, setTab] = useState<(typeof views)[number]>('Chats');
  const tabs = useRef<Array<HTMLButtonElement | null>>([]);
  const children = entries.filter(entry => entry.parent_notebook_id === notebook.id);
  if (summaries[notebook.id]) children.push(originalNotebookChat(notebook));
  const chats = recentChats(children, summaries).sort((a, b) => Number(b.pinned) - Number(a.pinned));
  const [artifacts, setArtifacts] = useState<{ id: string; title: string; kind: string; updated_at: string }[] | null>(null);
  const [canvases, setCanvases] = useState<CanvasSummaries['canvases'] | null>(null);
  const [canvasTitle, setCanvasTitle] = useState('');
  const [creatingCanvas, setCreatingCanvas] = useState(false);
  const [canvasError, setCanvasError] = useState('');
  const [canvasToRemove, setCanvasToRemove] = useState<CanvasSummaries['canvases'][number] | null>(null);
  const [deletingCanvas, setDeletingCanvas] = useState(false);
  const canvasController = useRef(new AbortController());
  const deletionInFlight = useRef(false);
  const [kinds, setKinds] = useState<readonly string[]>(['notes']);
  const [kind, setKind] = useState('notes');
  const [title, setTitle] = useState('');
  const [creating, setCreating] = useState(false);
  const [artifactError, setArtifactError] = useState('');
  const [removing, setRemoving] = useState('');
  const artifactController = useRef(new AbortController());
  const [selectedArtifacts, setSelectedArtifacts] = useState<readonly string[]>([]);
  const [selectedCanvases, setSelectedCanvases] = useState<readonly string[]>([]);
  const [exporting, setExporting] = useState(false);
  const [exportStatus, setExportStatus] = useState('');
  const [exportError, setExportError] = useState('');
  const exportController = useRef(new AbortController());

  useEffect(() => {
    const controller = new AbortController();
    canvasController.current = controller;
    return () => controller.abort();
  }, [notebook.id]);

  async function downloadExport() {
    if (locked || exporting) return;
    setExporting(true); setExportError(''); setExportStatus('');
    try {
      await downloadProjectExport(notebook.id, notebook.name, [...selectedArtifacts],
        [...selectedCanvases], exportController.current.signal);
      setExportStatus('Project export downloaded.');
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 0) {
        setExportError('Could not download the project export. Try again with fewer items.');
      }
    } finally { setExporting(false); }
  }

  function toggle(list: readonly string[], setList: (value: readonly string[]) => void, id: string) {
    setList(list.includes(id) ? list.filter(entry => entry !== id) : [...list, id]);
  }
  useEffect(() => {
    if (tab !== 'Documents' && tab !== 'Export') return;
    const request = new AbortController();
    readArtifacts(notebook.id, request.signal)
      .then(list => { setArtifacts(list.artifacts); setKinds(list.kinds); })
      .catch(() => { if (request.signal.aborted) return; setArtifacts([]); setArtifactError('Could not list documents. Try again.'); });
    return () => request.abort();
  }, [tab, notebook.id]);

  useEffect(() => {
    if (tab !== 'Canvas' && tab !== 'Export') return;
    const request = new AbortController();
    readCanvases(notebook.id, request.signal)
      .then(list => { setCanvases(list.canvases); })
      .catch(() => { if (request.signal.aborted) return; setCanvases([]); setCanvasError('Could not list canvases. Try again.'); });
    return () => request.abort();
  }, [tab, notebook.id]);

  async function newCanvas() {
    if (locked || creatingCanvas || !canvasTitle.trim()) return;
    setCreatingCanvas(true); setCanvasError('');
    try {
      const created = await createCanvas(notebook.id, canvasTitle.trim(),
        { nodes: [], edges: [] }, canvasController.current.signal);
      setCanvasTitle('');
      openCanvas(created.id);
    } catch { setCanvasError('Could not create the canvas. Try again.'); }
    finally { setCreatingCanvas(false); }
  }

  async function removeCanvas() {
    if (locked || !canvasToRemove || deletionInFlight.current) return;
    deletionInFlight.current = true;
    setDeletingCanvas(true);
    setCanvasError('');
    const signal = canvasController.current.signal;
    try {
      if ((await currentSession(signal)).owner_id !== owner) {
        expired();
        return;
      }
      const removed = await deleteCanvas(notebook.id, canvasToRemove.id, canvasToRemove.revision, signal);
      if (signal.aborted) return;
      setCanvases(list => list?.filter(entry => entry.id !== removed.id) ?? null);
      setSelectedCanvases(selection => selection.filter(id => id !== removed.id));
    } catch (error) {
      if (signal.aborted) return;
      if (error instanceof ApiError && [401, 403].includes(error.status)) {
        expired();
        return;
      }
      try {
        const latest = await readCanvases(notebook.id, signal);
        if (signal.aborted) return;
        if (latest.owner_id !== owner) { expired(); return; }
        setCanvases(latest.canvases);
        setSelectedCanvases(selection => selection.filter(id => latest.canvases.some(canvas => canvas.id === id)));
        if (latest.canvases.some(canvas => canvas.id === canvasToRemove.id)) {
          setCanvasError('The canvas was not deleted. Check the current canvas before trying again.');
        }
      } catch {
        if (!signal.aborted) setCanvasError('Could not confirm the deletion. Reopen this tab to check your saved canvases.');
      }
    } finally {
      deletionInFlight.current = false;
      setDeletingCanvas(false);
      setCanvasToRemove(null);
    }
  }

  async function newDocument() {
    if (locked || creating || !title.trim()) return;
    setCreating(true); setArtifactError('');
    try {
      const created = await createArtifact(title.trim(), kind);
      setTitle('');
      openArtifact(created.id);
    } catch { setArtifactError('Could not create the document. Try again.'); }
    finally { setCreating(false); }
  }

  async function copyArtifact(id: string) {
    setArtifactError('');
    try {
      const copied = await duplicateArtifact(notebook.id, id, artifactController.current.signal);
      openArtifact(copied.id);
    } catch { setArtifactError('Could not duplicate the document. Try again.'); }
  }

  async function removeArtifact(id: string) {
    setArtifactError('');
    try {
      const removed = await deleteArtifact(notebook.id, id, artifactController.current.signal);
      setArtifacts(list => list?.filter(entry => entry.id !== removed.id) ?? null);
      setRemoving('');
    } catch { setArtifactError('Could not delete the document. Refresh and try again.'); }
  }

  return <section className="notebook-page" aria-labelledby="folder-title">
    <header className="folder-heading">
      <h1 id="folder-title"><Icon name="folder"/><span>{notebook.name}</span></h1>
      <button className="primary folder-new-chat" disabled={locked} onClick={createChat}>
        <Icon name="plus"/> New chat in this notebook
      </button>
    </header>
    <div className="folder-tabs" role="tablist" aria-label="Notebook views">
      {views.map((view, index) => <button key={view} type="button" ref={element => { tabs.current[index] = element; }}
        id={`folder-tab-${view}`} role="tab" aria-selected={tab === view} aria-controls={`folder-panel-${view}`}
        tabIndex={tab === view ? 0 : -1} onClick={() => setTab(view)} onKeyDown={event => {
          if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
          event.preventDefault();
          const next = event.key === 'Home' ? 0 : event.key === 'End' ? views.length - 1
            : (index + (event.key === 'ArrowLeft' ? views.length - 1 : 1)) % views.length;
          setTab(views[next]);
          tabs.current[next]?.focus();
        }}>{view}</button>)}
    </div>
    <section id="folder-panel-Chats" role="tabpanel" aria-labelledby="folder-tab-Chats" tabIndex={0} hidden={tab !== 'Chats'}>
      {chats.length ? <ul className="folder-chats">{chats.map(chat => {
        const summary = summaries[chat.id];
        const date = new Date(summary?.activity_at ?? '');
        const when = relativeTime(summary?.activity_at);
        return <li key={chat.id}><button className="folder-chat" disabled={locked} onClick={() => openChat(chat.id)}>
          <span className="folder-chat-text">
            <strong>{chat.name}{chat.pinned ? <Icon name="pin"/> : null}</strong>
            {summary?.preview ? <span className="folder-chat-preview">{summary.preview}</span> : null}
          </span>
          {when ? <time dateTime={date.toISOString()} title={date.toLocaleString()}>{when}</time> : null}
        </button></li>;
      })}</ul> : <p className="folder-empty supporting">Start a chat here to use this notebook’s shared sources.</p>}
    </section>
    <section id="folder-panel-Documents" role="tabpanel" aria-labelledby="folder-tab-Documents" tabIndex={0} hidden={tab !== 'Documents'}>
      <form className="folder-new-document" onSubmit={event => {
        event.preventDefault();
        if (title.trim()) void newDocument();
      }}>
        <label htmlFor="folder-document-title">New document title</label>
        <input id="folder-document-title" maxLength={200} value={title} placeholder="e.g. Field notes"
          onChange={event => setTitle(event.target.value)} disabled={locked || creating}/>
        <label htmlFor="folder-document-kind" className="sr-only">Document type</label>
        <select id="folder-document-kind" value={kind} disabled={locked || creating}
          onChange={event => setKind(event.target.value)}>
          {kinds.map(option => <option key={option} value={option}>{KIND_LABELS[option] ?? option}</option>)}
        </select>
        <button className="primary" type="submit" disabled={locked || creating || !title.trim()}>
          {creating ? 'Creating…' : 'New document'}
        </button>
      </form>
      {artifactError ? <p role="alert">{artifactError}</p> : null}
      {artifacts === null ? <p className="folder-empty supporting" role="status">Checking documents…</p> : artifacts.length
        ? <ul className="folder-chats">{artifacts.map(artifact => <li key={artifact.id}>
            <button className="folder-chat" disabled={locked} onClick={() => openArtifact(artifact.id)}>
              <span className="folder-chat-text"><strong>{artifact.title}</strong>
                <span className="supporting">{KIND_LABELS[artifact.kind] ?? artifact.kind}</span></span>
              <time dateTime={artifact.updated_at} title={artifact.updated_at}>{relativeTime(artifact.updated_at)}</time>
            </button>
            <div className="source-row-actions">
              <button disabled={locked} onClick={() => void copyArtifact(artifact.id)}>
                <Icon name="copy"/> Duplicate
              </button>
              {removing === artifact.id ? <>
                <button className="danger-action" disabled={locked} onClick={() => void removeArtifact(artifact.id)}>Confirm delete</button>
                <button onClick={() => setRemoving('')}>Cancel</button>
              </> : <button className="danger-action" disabled={locked} onClick={() => setRemoving(artifact.id)}>
                <Icon name="trash"/> Delete
              </button>}
            </div>
          </li>)}</ul>
        : <p className="folder-empty supporting">No documents yet. Create one to draft your project writing.</p>}
    </section>
    <section id="folder-panel-Canvas" role="tabpanel" aria-labelledby="folder-tab-Canvas" tabIndex={0} hidden={tab !== 'Canvas'}>
      <form className="folder-new-document" onSubmit={event => {
        event.preventDefault();
        if (canvasTitle.trim()) void newCanvas();
      }}>
        <label htmlFor="folder-canvas-title">New canvas title</label>
        <input id="folder-canvas-title" maxLength={200} value={canvasTitle} placeholder="e.g. Crossing concepts"
          onChange={event => setCanvasTitle(event.target.value)} disabled={locked || creatingCanvas}/>
        <button className="primary" type="submit" disabled={locked || creatingCanvas || !canvasTitle.trim()}>
          {creatingCanvas ? 'Creating…' : 'New canvas'}
        </button>
      </form>
      {canvasError ? <p role="alert">{canvasError}</p> : null}
      {canvases === null ? <p className="folder-empty supporting" role="status">Checking canvases…</p> : canvases.length
        ? <ul className="folder-chats">{canvases.map(canvas => <li key={canvas.id}>
            <button className="folder-chat" disabled={locked || deletingCanvas} onClick={() => openCanvas(canvas.id)}>
              <span className="folder-chat-text"><strong>{canvas.title}</strong>
                <span className="supporting">Design canvas</span></span>
              <time dateTime={canvas.updated_at} title={canvas.updated_at}>{relativeTime(canvas.updated_at)}</time>
            </button>
            <div className="source-row-actions">
              {canvasToRemove?.id === canvas.id ? <>
                <p className="supporting">Delete this canvas and its history? Existing evidence links will show as unavailable.</p>
                <button type="button" className="danger-action" disabled={locked || deletingCanvas}
                  onClick={() => void removeCanvas()}>Confirm canvas deletion</button>
                <button type="button" disabled={deletingCanvas} onClick={() => setCanvasToRemove(null)}>Cancel</button>
              </> : <button type="button" className="danger-action" disabled={locked || deletingCanvas}
                aria-label={`Delete canvas: ${canvas.title}`} onClick={() => setCanvasToRemove(canvas)}>
                <Icon name="trash"/> Delete
              </button>}
            </div>
          </li>)}</ul>
        : <p className="folder-empty supporting">No canvases yet. Create one to map your project reasoning.</p>}
    </section>
    <section id="folder-panel-Sources" role="tabpanel" aria-labelledby="folder-tab-Sources" tabIndex={0} hidden={tab !== 'Sources'}>
      {tab === 'Sources' ? <Sources embedded thread={notebook.id} owner={owner} disabled={locked} expired={expired}/> : null}
    </section>
    <section id="folder-panel-Export" role="tabpanel" aria-labelledby="folder-tab-Export" tabIndex={0} hidden={tab !== 'Export'}>
      {tab === 'Export' ? <>
        <p className="supporting">Choose the saved documents and canvases to include. The export
          also carries this notebook's conversation, summary, Thinking Path and cited sources.</p>
        {exportError ? <p role="alert">{exportError}</p> : null}
        {exportStatus ? <p role="status">{exportStatus}</p> : null}
        {artifacts === null || canvases === null ? <p className="folder-empty supporting" role="status">Checking saved work…</p> : null}
        {artifacts?.length ? <fieldset>
          <legend>Documents</legend>
          {artifacts.map(artifact => <label key={artifact.id}>
            <input type="checkbox" checked={selectedArtifacts.includes(artifact.id)}
              disabled={locked || exporting} onChange={() => toggle(selectedArtifacts, setSelectedArtifacts, artifact.id)}/>
            {' '}Include {artifact.title}
          </label>)}
        </fieldset> : null}
        {canvases?.length ? <fieldset>
          <legend>Canvases</legend>
          {canvases.map(canvas => <label key={canvas.id}>
            <input type="checkbox" checked={selectedCanvases.includes(canvas.id)}
              disabled={locked || exporting} onChange={() => toggle(selectedCanvases, setSelectedCanvases, canvas.id)}/>
            {' '}Include {canvas.title}
          </label>)}
        </fieldset> : null}
        <button className="primary" disabled={locked || exporting}
          onClick={() => void downloadExport()}>
          {exporting ? 'Preparing…' : 'Download project export'}
        </button>
      </> : null}
    </section>
  </section>;
}
