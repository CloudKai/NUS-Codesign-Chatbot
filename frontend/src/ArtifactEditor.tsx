/** Persistent student document editor over the routed artifact URL with debounced confirmed autosave. */
import { useEditor, EditorContent, type Content, type Editor } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import Link from '@tiptap/extension-link';
import { useEffect, useRef, useState, type ComponentProps } from 'react';
import { Icon } from './Icon';
import { ApiError, currentSession, type Artifact, type ArtifactVersion, type ArtifactVersionSummary } from './api';
import { readArtifact, readArtifactVersion, readArtifactVersions, restoreArtifactVersion,
  downloadArtifactExport, saveArtifact, readSources } from './api/client';
import { readDraft, useArtifactAutosave, type AutosaveState } from './useArtifactAutosave';
import { ArtifactToCanvasDialog } from './ArtifactToCanvasDialog';
import type { EvidenceReference, Source } from './api';

/** One keyboard-accessible formatting control with a truthful pressed state. */
function ToolButton({ editor, label, icon, active, run }: {
  editor: Editor | null; label: string; icon: ComponentProps<typeof Icon>['name'];
  active: boolean; run: (editor: Editor) => boolean;
}) {
  return <button type="button" aria-label={label} title={label} aria-pressed={active} disabled={!editor}
    onClick={() => run(editor as Editor)}>
    <Icon name={icon}/>
  </button>;
}

/** Truthful autosave indicator: every state is distinguishable and none claims an unconfirmed save. */
function saveNotice(state: AutosaveState): string {
  if (state === 'saving') return 'Saving…';
  if (state === 'saved') return 'All changes saved.';
  if (state === 'offline') return 'You appear to be offline. Your edits are kept in this tab and save when you continue.';
  if (state === 'failure') return 'Automatic saving failed. Press Save to try again.';
  if (state === 'conflict') return 'This document changed in another tab. Resolve the conflict below.';
  return 'Editing — changes save automatically as you write.';
}

interface ArtifactEditorProps {
  owner: string; threadId: string; artifactId: string; expired: () => void; onClose: () => void;
  onDiscuss?: (artifactId: string, revision: number, paragraph: number | null, label: string) => void;
}

/** Use a fresh editor and save queue when the owner, notebook or document changes. */
export function ArtifactEditor(props: ArtifactEditorProps) {
  return <ArtifactEditorInner key={JSON.stringify([props.owner, props.threadId, props.artifactId])} {...props}/>;
}

/** Load, edit and autosave one owned artifact; conflicts keep the student's draft until resolved. */
function ArtifactEditorInner({ owner, threadId, artifactId, expired, onClose, onDiscuss }: ArtifactEditorProps) {
  const [artifact, setArtifact] = useState<Artifact | null>(null);
  const [linkUrl, setLinkUrl] = useState('');
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const [busy, setBusy] = useState(false);
  const [title, setTitle] = useState('');
  const titleRef = useRef('');
  const [restored, setRestored] = useState(false);
  const controller = useRef(new AbortController());
  const active = useRef(true);
  const pendingContent = useRef<Content | null>(null);
  useEffect(() => {
    active.current = true;
    return () => { active.current = false; controller.current.abort(); };
  }, []);
  const editor = useEditor({
    // The vendored ProseMirror base styles live in styles.css; runtime injection
    // would violate the production CSP `style-src 'self'`.
    injectCSS: false,
    extensions: [StarterKit, Link.configure({
      openOnClick: false,
      // Safe links only: the canonical document never carries script URLs.
      validate: url => /^(https?:\/\/|\/)/.test(url),
    })],
    content: { type: 'doc', content: [] } as Content,
    editable: false,
  });

  async function verify() {
    const session = await currentSession(controller.current.signal);
    if (!active.current) throw new Error('Closed');
    if (session.owner_id !== owner) { expired(); throw new Error('Session changed'); }
  }

  function updateTitle(next: string) {
    titleRef.current = next;
    setTitle(next);
  }

  const [historyOpen, setHistoryOpen] = useState(false);
  const [versions, setVersions] = useState<ArtifactVersionSummary[] | null>(null);
  const [preview, setPreview] = useState<ArtifactVersion | null>(null);
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [sources, setSources] = useState<Source[] | null>(null);
  const [newSourceId, setNewSourceId] = useState('');
  const [canvasSource, setCanvasSource] = useState<number | null | 'closed'>('closed');

  /** Toggle the evidence panel and load the notebook's bounded source list once. */
  function toggleEvidence() {
    const opening = !evidenceOpen;
    setEvidenceOpen(opening);
    if (opening && sources === null) {
      readSources(threadId, controller.current.signal)
        .then(list => { if (active.current) setSources(list.sources); })
        .catch(error => {
          if (error instanceof ApiError && [401, 403].includes(error.status)) { expired(); return; }
          if (active.current) setError('Could not load sources. Try again.');
        });
    }
  }

  /** Attach or detach evidence while preserving each retained link's identity and revision. */
  async function applyReferences(references: EvidenceReference[]) {
    if (!artifact || busy || autosave.state === 'saving') return;
    setError(''); setBusy(true);
    try {
      const started = await autosave.applyExternalWrite(async saved => {
        await verify();
        const updated = await saveArtifact(threadId, artifactId, saved.document,
          saved.revision, null, controller.current.signal, references.map(reference => ({
            kind: reference.kind, id: reference.id,
            ...(reference.canvas_id ? { canvas_id: reference.canvas_id } : {}),
            ...(reference.revision !== undefined ? { revision: reference.revision } : {}),
          })));
        await verify();
        return updated;
      }, confirmed => {
        pendingContent.current = null;
        setArtifact(confirmed); updateTitle(confirmed.title);
        setStatus('Evidence updated.');
      });
      if (!started) setError('Save or resolve your document edits before changing evidence.');
    } catch (error) {
      if (error instanceof ApiError && [401, 403].includes(error.status)) { expired(); return; }
      if (error instanceof ApiError && error.status === 409) {
        if (active.current) setError('This document changed while updating evidence. Reload it first.');
        return;
      }
      if (active.current) setError('Could not update the evidence list. Try again.');
    } finally { if (active.current) setBusy(false); }
  }

  /** Load the bounded version history when the panel opens; versions are metadata only. */
  function toggleHistory() {
    const opening = !historyOpen;
    setHistoryOpen(opening);
    setPreview(null);
    if (opening && versions === null) {
      readArtifactVersions(threadId, artifactId, controller.current.signal)
        .then(list => { if (active.current) setVersions(list.versions); })
        .catch(error => {
          if (error instanceof ApiError && [401, 403].includes(error.status)) { expired(); return; }
          if (active.current) setError('Could not load version history. Try again.');
        });
    }
  }

  async function openPreview(revision: number) {
    try {
      const value = await readArtifactVersion(threadId, artifactId, revision, controller.current.signal);
      await verify();
      if (active.current) setPreview(value);
    } catch (error) {
      if (error instanceof ApiError && [401, 403].includes(error.status)) { expired(); return; }
      if (active.current) setError('Could not open that version. Try again.');
    }
  }

  /** Restore as a new revision guarded by the current one; intermediates stay in history. */
  async function restore(revision: number) {
    if (!artifact || busy) return;
    setBusy(true); setError('');
    try {
      const started = await autosave.applyExternalWrite(async saved => {
        await verify();
        const restored = await restoreArtifactVersion(threadId, artifactId, revision,
          saved.revision, controller.current.signal);
        await verify();
        return restored;
      }, confirmed => {
        pendingContent.current = confirmed.document as Content;
        setArtifact(confirmed); updateTitle(confirmed.title); setPreview(null);
        setStatus(`Restored version ${revision}.`);
      });
      if (!started) setError('Save or resolve your document edits before restoring an earlier version.');
    } catch (error) {
      if (error instanceof ApiError && [401, 403].includes(error.status)) { expired(); return; }
      if (error instanceof ApiError && error.status === 409) {
        if (active.current) setError('This document changed while restoring. Reload it before trying again.');
        return;
      }
      if (active.current) setError('Could not restore that version. Try again.');
    } finally { if (active.current) setBusy(false); }
  }

  const autosave = useArtifactAutosave({
    owner,
    artifact,
    document: () => (editor?.getJSON() ?? { type: 'doc', content: [] }) as unknown,
    title: () => titleRef.current,
    enabled: !!artifact && !!editor,
    onSave: (document, savedTitle, revision) => saveArtifact(threadId, artifactId,
      document as Artifact['document'], revision, savedTitle || null, controller.current.signal),
    getSavedDocument: saved => saved.document,
    onConfirmed: confirmed => setArtifact(confirmed),
    readSaved: async () => {
      const latest = await readArtifact(threadId, artifactId, controller.current.signal);
      await verify();
      return latest;
    },
    onDiscard: latest => {
      pendingContent.current = latest.document as Content;
      setArtifact(latest);
      updateTitle(latest.title);
      setRestored(false); setStatus('Loaded the saved document.');
    },
    onExpired: expired,
  });

  // Load the saved artifact, then restore this owner's unsaved draft from this browser if one exists.
  useEffect(() => {
    setArtifact(null); setError(''); setStatus('Opening document…'); setRestored(false);
    readArtifact(threadId, artifactId, controller.current.signal)
      .then(async value => {
        await verify();
        if (!active.current) return;
        const draft = readDraft(owner, artifactId);
        const recovered = draft && (draft.document as Artifact['document']).type === 'doc' ? draft : null;
        setArtifact(value); updateTitle(recovered?.title ?? value.title);
        pendingContent.current = (recovered?.document ?? value.document) as Content;
        setRestored(!!recovered);
        if (recovered) autosave.restoreDraft(value, recovered);
        setStatus('');
      })
      .catch(error => {
        if (!active.current) return;
        if (error instanceof ApiError && [401, 403].includes(error.status)) { expired(); return; }
        setError('Could not open this document. It may have been removed or belongs to another workspace.');
      });
  }, [artifactId, threadId]);

  const loadedArtifact = useRef<string | null>(null);
  useEffect(() => {
    if (!artifact || !editor) return;
    // Confirmed autosaves reconcile the revision only; content loads on first open or explicit handoff.
    if (loadedArtifact.current === artifact.id && !pendingContent.current) return;
    loadedArtifact.current = artifact.id;
    editor.commands.setContent((pendingContent.current ?? artifact.document) as Content, { emitUpdate: false });
    pendingContent.current = null;
    editor.setEditable(true, false);
  }, [artifact, editor]);

  useEffect(() => {
    if (!editor) return;
    const onUpdate = () => {
      setStatus(''); autosave.markDirty();
    };
    editor.on('update', onUpdate);
    return () => { editor.off('update', onUpdate); };
  }, [editor, autosave]);

  /** One explicit save per action; the confirmed response reconciles without replaying the write. */
  function save() {
    if (!editor || !artifact || busy || autosave.state === 'saving') return;
    setError('');
    autosave.saveNow();
  }

  async function resolveConflict(resolve: () => Promise<void>) {
    setError(''); setStatus('');
    try { await resolve(); }
    catch { if (active.current) setError('Could not resolve the conflict. Try again.'); }
  }

  /** Download the current saved artifact in one of the three reviewed formats. */
  async function download(format: 'markdown' | 'text' | 'json') {
    if (!artifact || busy) return;
    setBusy(true); setError('');
    try {
      await verify();
      await downloadArtifactExport(threadId, artifactId, format, title || 'artifact',
        controller.current.signal);
      await verify();
      if (active.current) setStatus(`Exported as ${format}.`);
    } catch (error) {
      if (error instanceof ApiError && [401, 403].includes(error.status)) { expired(); return; }
      if (active.current) setError('Could not export this document. Try again.');
    } finally { if (active.current) setBusy(false); }
  }

  const conflict = autosave.state === 'conflict';
  return <section className="artifact-editor" aria-label="Document editor">
    <header className="artifact-header">
      <button className="icon-button" aria-label="Back to notebook" onClick={onClose}><Icon name="close"/></button>
      <input className="artifact-title" aria-label="Document title" maxLength={200} value={title}
        disabled={conflict || !artifact || busy} onChange={event => {
          setStatus(''); updateTitle(event.target.value); autosave.markDirty();
        }}/>
      <button className="primary" disabled={conflict || !artifact || busy} onClick={save}>
        {autosave.state === 'saving' ? 'Saving…' : 'Save'}
      </button>
      <button aria-expanded={historyOpen} aria-controls="artifact-history"
        onClick={toggleHistory} disabled={!artifact}>
        <Icon name="search"/> History
      </button>
      <button aria-expanded={evidenceOpen} aria-controls="artifact-evidence"
        onClick={toggleEvidence} disabled={!artifact}>
        <Icon name="book"/> Evidence
      </button>
    </header>
    {error ? <p role="alert">{error}</p> : null}
    {restored ? <p role="status">Restored your unsaved edits from this browser.</p> : null}
    <p role="status">{conflict ? saveNotice(autosave.state) : status || saveNotice(autosave.state)}</p>
    {conflict ? <div role="alert" className="artifact-conflict">
      <p>Your edits in this tab were not saved because the document changed elsewhere. Your version is still shown.</p>
      <button onClick={() => void resolveConflict(autosave.resolveByReload)}>Reload the saved document</button>
      <button onClick={() => void resolveConflict(autosave.resolveByKeep)}>Keep my edits and save over</button>
    </div> : null}
    {artifact && editor ? <div className="artifact-toolbar" role="toolbar" aria-label="Formatting">      <ToolButton editor={editor} label="Undo" icon="refresh" active={false}
        run={current => current.chain().focus().undo().run()}/>
      <ToolButton editor={editor} label="Redo" icon="refresh" active={false}
        run={current => current.chain().focus().redo().run()}/>
      <ToolButton editor={editor} label="Bold" icon="edit" active={editor.isActive('bold')}
        run={current => current.chain().focus().toggleBold().run()}/>
      <ToolButton editor={editor} label="Italic" icon="edit" active={editor.isActive('italic')}
        run={current => current.chain().focus().toggleItalic().run()}/>
      <ToolButton editor={editor} label="Heading" icon="document" active={editor.isActive('heading', { level: 2 })}
        run={current => current.chain().focus().toggleHeading({ level: 2 }).run()}/>
      <ToolButton editor={editor} label="Subheading" icon="document" active={editor.isActive('heading', { level: 3 })}
        run={current => current.chain().focus().toggleHeading({ level: 3 }).run()}/>
      <ToolButton editor={editor} label="Bulleted list" icon="more" active={editor.isActive('bulletList')}
        run={current => current.chain().focus().toggleBulletList().run()}/>
      <ToolButton editor={editor} label="Numbered list" icon="more" active={editor.isActive('orderedList')}
        run={current => current.chain().focus().toggleOrderedList().run()}/>
      <input className="artifact-link-url" aria-label="Link address" placeholder="https://"
        value={linkUrl} onChange={event => setLinkUrl(event.target.value)}/>
      <ToolButton editor={editor} label="Add link" icon="book" active={editor.isActive('link')}
        run={current => {
          const url = linkUrl.trim();
          if (!url) return false;
          return current.chain().focus().setLink({ href: url }).run();
        }}/>
      <ToolButton editor={editor} label="Remove link" icon="close" active={false}
        run={current => current.chain().focus().unsetLink().run()}/>
      {onDiscuss && artifact ? <>
        <button aria-label="Ask the coach about this document"
          title="Ask the coach about this whole document"
          onClick={() => onDiscuss(artifact.id, artifact.revision, null, artifact.title)}>
          Ask the coach</button>
        <button aria-label="Ask the coach about the selected paragraph"
          title="Ask the coach about the paragraph your cursor is in"
          onClick={() => {
            let paragraph: number | null = null;
            try { paragraph = editor.state.selection.$from.index(0); }
            catch { paragraph = null; }
            if (paragraph === null) return;
            onDiscuss(artifact.id, artifact.revision, paragraph,
              `paragraph ${paragraph + 1} of ${artifact.title}`);
          }}>Ask about this paragraph</button>
      </> : null}
      {artifact ? <button aria-label="Add to canvas"
        title="Add saved document content to a design canvas"
        onClick={() => {
          let paragraph: number | null = null;
          try { paragraph = editor.state.selection.$from.index(0); }
          catch { paragraph = null; }
          setCanvasSource(paragraph ?? null);
        }}>Add to canvas</button> : null}
    </div> : null}
    {artifact && evidenceOpen ? <section className="artifact-history" id="artifact-evidence" aria-label="Evidence links">
      <h3>Evidence</h3>
      <p className="supporting">Linked course material stays traceable; removed sources show as unavailable instead of disappearing silently.</p>
      {artifact.references.length
        ? <ul>{artifact.references.map((reference, index) => <li key={`${reference.kind}-${reference.id}`}>
            <span>{reference.available === false
              ? 'Unavailable or outdated evidence'
              : `${reference.title ?? reference.id}`}</span>
            <button disabled={busy || conflict}
              onClick={() => void applyReferences(artifact.references
                .filter((_entry, position) => position !== index))}>
              Detach
            </button>
          </li>)}</ul>
        : <p className="supporting">No evidence linked yet.</p>}
      <div className="artifact-evidence-add">
        {sources === null ? <p role="status" className="supporting">Checking sources…</p> : sources.length
          ? <select aria-label="Source to link" value={newSourceId}
              onChange={event => setNewSourceId(event.target.value)}>
              <option value="">Choose a source…</option>
              {sources.map(source => <option key={source.id} value={source.id}>{source.title}</option>)}
            </select>
          : <p className="supporting">This notebook has no sources yet.</p>}
        <button disabled={busy || conflict || !newSourceId} onClick={() => {
          const references = [...artifact.references
            .filter(entry => !(entry.kind === 'source' && entry.id === newSourceId)),
            { kind: 'source' as const, id: newSourceId }];
          void applyReferences(references).then(() => { if (active.current) setNewSourceId(''); });
        }}>Link source</button>
      </div>
    </section> : null}
    {artifact && historyOpen ? <section className="artifact-history" id="artifact-history" aria-label="Version history">
      <h3>Version history</h3>
      {versions === null ? <p role="status" className="supporting">Checking versions…</p> : versions.length
        ? <ul>{versions.map(entry => <li key={entry.revision}>
            <button aria-pressed={preview?.revision === entry.revision} disabled={conflict}
              onClick={() => void openPreview(entry.revision)}>
              Version {entry.revision} · {KIND_LABELS[entry.kind] ?? entry.kind} ·{' '}
              {entry.origin === 'restore' ? `restored from ${entry.restored_from}` : 'saved'} ·{' '}
              {new Date(entry.created_at).toLocaleString()}
            </button>
          </li>)}</ul>
        : <p className="supporting">No earlier versions yet.</p>}
      {preview ? <div className="artifact-version-preview">
        <p className="supporting">Previewing version {preview.revision} — nothing changes until you restore.</p>
        <pre>{previewText(preview.document)}</pre>
        <button disabled={conflict || busy} onClick={() => void restore(preview.revision)}>
          Restore version {preview.revision}
        </button>
        <button onClick={() => setPreview(null)}>Close preview</button>
      </div> : null}
    </section> : null}
    {artifact ? <div className="artifact-export" role="group" aria-label="Export document">
      <button disabled={busy} onClick={() => void download('markdown')}>Export Markdown</button>
      <button disabled={busy} onClick={() => void download('text')}>Export plain text</button>
      <button disabled={busy} onClick={() => void download('json')}>Export JSON</button>
    </div> : null}
    {artifact ? <EditorContent editor={editor}/> : null}
    {artifact && canvasSource !== 'closed' ? <ArtifactToCanvasDialog threadId={threadId}
      artifact={artifact} initialParagraph={canvasSource}
      onClose={() => setCanvasSource('closed')}/> : null}
  </section>;
}

/** Curriculum-facing labels for the supported artifact types. */
const KIND_LABELS: Record<string, string> = {
  notes: 'General notes',
  problem_identification: 'Problem identification',
  concept_generation: 'Concept generation',
  design_specification: 'Design specification',
  ethics_critical_thinking: 'Ethics & critical thinking',
  reflection: 'Reflection',
};

/** Bounded plain-text projection of one version's canonical document for the preview. */
function previewText(document: ArtifactVersion['document']): string {
  const lines: string[] = [];
  const walk = (node: { type?: unknown; content?: unknown; text?: unknown }, depth: number): void => {
    if (Array.isArray(node.content)) {
      for (const child of node.content) walk(child as typeof node, depth + 1);
      return;
    }
    if (typeof node.text === 'string') lines.push(`${'  '.repeat(depth)}${node.text}`);
  };
  walk(document, 0);
  return lines.join('\n') || '(empty document)';
}
