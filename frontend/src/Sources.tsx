/** Notebook-scoped source work independent of the mounted conversation and composer. */
import { Icon } from './Icon';
import { useEffect, useRef, useState } from 'react';
import { ApiError, currentSession, get } from './api';
import './sources.css';

interface Source { id: string; title: string; selected: boolean; locked: boolean; kind: string; size: number }
interface SourceList { owner_id: string; thread_id: string; sources: Source[]; max_files: number; max_file_bytes: number }
interface Job { id: string; filenames: string[]; state: 'queued' | 'processing' | 'saved' | 'failed'; retryable: boolean }
interface Jobs { owner_id: string; thread_id: string; jobs: Job[] }
interface Detail { source: Source; text: string; truncated: boolean }

/** Format source metadata for a quick file scan. */
function fileDescription(source: Source) {
  if (source.locked) return 'Official course material';
  const type = source.kind === 'image' ? 'Image' : source.kind === 'url' ? 'Web page' : source.kind === 'text' ? 'Note' : 'Document';
  if (!source.size) return type;
  const units = source.size < 1024 ? [source.size, 'B'] as const
    : source.size < 1048576 ? [source.size / 1024, 'KB'] as const : [source.size / 1048576, 'MB'] as const;
  return `${type} · ${units[0].toLocaleString(undefined, { maximumFractionDigits: 1 })} ${units[1]}`;
}

/** Show safe source controls while keeping drafts, transcript, and source authority separate. */
export function Sources({ owner, thread, expired, uncertain, opened, disabled, library = false, embedded = false }: {
  disabled: boolean; owner: string; thread: string; expired: () => void; uncertain?: (value: boolean) => void; opened?: () => void;
  library?: boolean; embedded?: boolean;
}) {
  const panel = !library && !embedded;
  const [open, setOpen] = useState(!panel);
  const [list, setList] = useState<SourceList | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [removing, setRemoving] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [unverified, setUnverified] = useState(false);
  const [notice, setNotice] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [addingFiles, setAddingFiles] = useState(false);
  const [loadingLibrary, setLoadingLibrary] = useState(false);
  const [query, setQuery] = useState('');
  const [actionsFor, setActionsFor] = useState('');
  const [libraryChoices, setLibraryChoices] = useState<Source[] | null>(null);
  const active = useRef(true);
  const lock = useRef(false);
  const controller = useRef(new AbortController());
  const trigger = useRef<HTMLButtonElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const detailHeading = useRef<HTMLHeadingElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const uploadToggle = useRef<HTMLButtonElement>(null);
  const scroll = useRef(0);
  const sequence = useRef(0);
  const path = `/api/v1/reader/threads/${encodeURIComponent(thread)}`;
  const fileId = library ? 'library-files' : embedded ? 'notebook-files' : 'source-files';
  const visibleJobs = jobs.filter(job => job.state !== 'saved');
  const blocked = busy || unverified || disabled;
  const documents = list?.sources.filter(source => !source.locked) ?? [];
  const course = list?.sources.filter(source => source.locked) ?? [];
  const activeCount = documents.filter(source => source.selected).length;
  const filter = query.trim().toLocaleLowerCase();
  const matches = (source: Source) => source.title.toLocaleLowerCase().includes(filter);
  const available = libraryChoices?.filter(source => !documents.some(link => link.id === source.id));

  async function verify() {
    const session = await currentSession(controller.current.signal);
    if (!active.current) throw new Error('Closed');
    if (session.owner_id !== owner) { expired(); throw new Error('Session changed'); }
  }

  function failure(error: unknown) {
    if (!active.current) return;
    if (error instanceof ApiError && [401, 403].includes(error.status)) expired();
    else setError(library ? 'Could not check your Library. Refresh when you’re back online.'
      : 'Could not check sources. Refresh when you’re back online.');
  }

  async function refresh() {
    const epoch = ++sequence.current;
    await verify();
    const [next, uploads] = await Promise.all([
      get<SourceList>(`${path}/sources`, controller.current.signal), get<Jobs>(`${path}/uploads`, controller.current.signal),
    ]);
    await verify();
    if (epoch !== sequence.current) return;
    if (next.owner_id !== owner || uploads.owner_id !== owner || next.thread_id !== thread || uploads.thread_id !== thread) {
      expired(); throw new Error('Session changed');
    }
    setList(next); setJobs(uploads.jobs);
    if (uploads.jobs.length && uploads.jobs.every(job => job.state === 'saved')) {
      setNotice(value => value.startsWith('Upload submitted.') ? '' : value);
    }
    setDetail(value => value && next.sources.some(source => source.id === value.source.id) ? value : null);
    setUnverified(false); uncertain?.(false); setError('');
  }

  async function act(route: string, body?: object | FormData) {
    if (lock.current || unverified || disabled) return;
    lock.current = true; setBusy(true); setError('');
    setUnverified(true); uncertain?.(true);
    // Invalidate older reads before a mutation; an ambiguous write is followed only by reads.
    sequence.current += 1;
    let submitted = false;
    try {
      await verify();
      const response = await fetch(`${path}/${route}`, {
        method: 'POST', credentials: 'same-origin', cache: 'no-store', signal: controller.current.signal,
        headers: body instanceof FormData || !body ? undefined : { 'Content-Type': 'application/json' },
        body: body instanceof FormData ? body : body ? JSON.stringify(body) : undefined,
      });
      submitted = true;
      await verify();
      if ([401, 403].includes(response.status)) { expired(); return; }
      const success = route === 'uploads' ? 'Upload submitted. Files appear below when ready.'
        : route.endsWith('/link') ? 'Source added and enabled.' : route.endsWith('/select') ? 'Source selection saved.'
        : route.endsWith('/remove') ? library ? 'File deleted.' : 'Source removed from this notebook.'
        : route.endsWith('/retry') ? 'Upload queued for retry.' : 'Upload dismissed.';
      setNotice(response.ok ? success
        : response.status === 429 ? 'Upload allowance is full or uploads are busy. Wait, or dismiss failed uploads and choose fewer or smaller files.'
        : response.status === 422 && route === 'uploads' ? 'An image could not be validated. Use a readable PNG, JPEG, WebP, or GIF under 24 megapixels.'
        : response.status === 413 || response.status === 400 ? 'Files exceed the upload limits. Choose fewer or smaller files.'
        : 'That source action is unavailable or changed. Saved sources refreshed.');
      await refresh();
      if (response.ok && route === 'uploads') setAddingFiles(false);
      return response.ok;
    } catch (error) {
      failure(error);
      setNotice('The action may have reached the server. Refresh sources before continuing. No action is replayed automatically.');
    } finally {
      if (active.current) {
        if (route === 'uploads') {
          setFiles([]); if (fileInput.current) fileInput.current.value = '';
          if (!submitted) setNotice('Upload outcome is unknown. Refresh sources and check filenames before selecting files again.');
        }
        setBusy(false);
      }
      lock.current = false;
    }
  }

  async function inspect(source: Source) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError('');
    try {
      await verify();
      const next = await get<Detail>(`${path}/sources/${encodeURIComponent(source.id)}`, controller.current.signal);
      await verify();
      if (next.source.id !== source.id) throw new Error('Source changed');
      setDetail(next); setRemoving(''); setActionsFor('');
    } catch (error) { failure(error); }
    finally { lock.current = false; if (active.current) setBusy(false); }
  }

  async function chooseFromLibrary() {
    setError('');
    setLoadingLibrary(true);
    try {
      await verify();
      const result = await get<SourceList>('/api/v1/reader/threads/library/sources', controller.current.signal);
      await verify();
      if (result.owner_id !== owner || result.thread_id !== 'library') throw new Error('Library changed');
      setLibraryChoices(result.sources);
    } catch (error) { failure(error); }
    finally { if (active.current) setLoadingLibrary(false); }
  }

  async function download(source: Source) {
    setError('');
    try {
      await verify();
      const response = await fetch(`${path}/sources/${encodeURIComponent(source.id)}/content`, {
        credentials: 'same-origin', cache: 'no-store', signal: controller.current.signal,
      });
      if (!response.ok) throw new ApiError(response.status);
      const blob = await response.blob(); await verify();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a'); link.href = url; link.download = source.title; link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) { failure(error); }
  }

  function close() {
    setOpen(false); setDetail(null); setRemoving(''); setFiles([]); setLibraryChoices(null);
    setAddingFiles(false); setActionsFor(''); setQuery('');
    trigger.current?.focus({ preventScroll: true }); window.scrollTo(0, scroll.current);
  }

  useEffect(() => {
    active.current = true;
    if (!panel) void refresh().catch(failure);
    return () => { active.current = false; sequence.current += 1; controller.current.abort(); };
  }, []);
  useEffect(() => {
    if (!open) return;
    if (!embedded) heading.current?.focus({ preventScroll: true });
    if (!panel) return;
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape' && !event.defaultPrevented) close(); };
    window.addEventListener('keydown', escape);
    return () => window.removeEventListener('keydown', escape);
  }, [open]);
  useEffect(() => { if (detail) detailHeading.current?.focus(); }, [detail]);
  useEffect(() => {
    if (!open || unverified || busy || !jobs.some(job => ['queued', 'processing'].includes(job.state))) return;
    const timer = window.setTimeout(() => { void refresh().catch(failure); }, 1200);
    return () => window.clearTimeout(timer);
  }, [open, jobs, unverified, busy]);

  function sourceRow(source: Source) {
    const viewing = detail?.source.id === source.id;
    const rowId = `${fileId}-${source.id}`;
    return <li key={source.id}>
      <div className="source-row">
        <button className="source-file" id={`${rowId}-preview`} disabled={busy} aria-expanded={viewing}
          title={`Preview ${source.title}`} aria-label={`Preview ${source.title}`}
          onClick={() => viewing ? setDetail(null) : void inspect(source)}>
          <span className="source-file-icon"><Icon name={source.kind === 'image' ? 'image' : source.locked ? 'book' : 'document'}/></span>
          <span className="source-file-text"><strong>{source.title}</strong><small>{fileDescription(source)}</small></span>
        </button>
        {!library && !source.locked ? <label className="source-use">
          <input type="checkbox" checked={source.selected} disabled={blocked} aria-label={`Use ${source.title} in answers`}
            onChange={event => void act(`sources/${encodeURIComponent(source.id)}/select`, { selected: event.target.checked })}/>
          <span aria-hidden="true">{source.selected ? 'In use' : 'Off'}</span>
        </label> : null}
        <button className="icon-button source-more" id={`${rowId}-more`} aria-label={`Actions for ${source.title}`}
          aria-expanded={actionsFor === source.id} title="File actions" onClick={() => {
            setActionsFor(actionsFor === source.id ? '' : source.id); setRemoving(''); setDetail(null);
          }}><Icon name="more"/></button>
      </div>
      {actionsFor === source.id ? <div className="source-row-actions">
        <button onClick={() => void download(source)}><Icon name="download"/> Download</button>
        {!source.locked ? <button className="danger-action" disabled={blocked} onClick={() => setRemoving(source.id)}>
          <Icon name={library ? 'trash' : 'close'}/> {library ? 'Delete file' : 'Remove from notebook'}
        </button> : null}
      </div> : null}
      {removing === source.id ? <div className="source-inline" role="group" aria-label={`Remove ${source.title}?`}>
        <p>{library ? 'Delete this file everywhere? Saved citations will remain, and the original will be unavailable.'
          : 'Remove this source from the notebook? The original stays in your Library.'}</p>
        <div className="source-row-actions">
          <button className="danger-action" disabled={blocked} onClick={() => {
            void act(`sources/${encodeURIComponent(source.id)}/remove`, library ? { confirmed: true } : undefined).then(saved => {
              if (saved && active.current) { setRemoving(''); setActionsFor(''); heading.current?.focus(); }
            });
          }}>{library ? 'Confirm deletion' : 'Confirm removal'}</button>
          <button onClick={() => { setRemoving(''); document.getElementById(`${rowId}-more`)?.focus(); }}>Cancel</button>
        </div>
      </div> : null}
      {viewing && detail ? <section className="source-inline source-detail" aria-label={`Preview of ${source.title}`}>
        <div className="source-section-title"><h3 ref={detailHeading} tabIndex={-1}>Extracted text</h3>
          <button className="icon-button" aria-label="Close preview" onClick={() => {
            setDetail(null); document.getElementById(`${rowId}-preview`)?.focus();
          }}><Icon name="close"/></button>
        </div>
        {detail.truncated ? <p className="supporting">Showing the first 24,000 characters.</p> : null}
        {detail.text ? <pre>{detail.text}</pre> : <p className="supporting">{source.kind === 'image' ? 'Download the image to view the original.' : 'There’s no extracted text to preview.'}</p>}
        <button onClick={() => void download(source)}><Icon name="download"/> Download original</button>
      </section> : null}
    </li>;
  }

  const Heading = library ? 'h1' : embedded ? 'h2' : 'h3';
  const panelId = library ? 'library-page' : embedded ? 'notebook-source-panel' : 'source-panel';
  return <>
    {panel ? <button className="source-trigger" aria-label="Sources" id="notebook-sources" ref={trigger}
      aria-expanded={open} aria-controls={panelId} onClick={() => {
        if (open) { close(); return; }
        scroll.current = window.scrollY; opened?.(); setOpen(true); if (!lock.current) void refresh().catch(failure);
      }}><Icon name="book"/> Sources</button> : null}
    {open ? <section id={panelId} className={`source-panel ${library ? 'library-page' : embedded ? 'folder-sources' : 'evidence source-drawer'}`}
      aria-label={library ? 'Library' : 'Notebook sources'}>
      <header className="source-header">
        <div>
          <Heading ref={heading} tabIndex={-1}>{library ? 'Library' : 'Notebook sources'}</Heading>
          <p>{library ? 'Your private files from uploads, notebooks, and chats.' : 'Choose which files this notebook can use in future answers.'}</p>
        </div>
        <div className="source-header-actions">
          <button className="icon-button" aria-label={library ? 'Refresh Library' : 'Refresh sources'}
            title={library ? 'Refresh Library' : 'Refresh sources'} disabled={busy} onClick={() => {
              setBusy(true); setNotice('');
              void refresh().catch(failure).finally(() => { if (active.current) setBusy(false); });
            }}><Icon name="refresh"/></button>
          {panel ? <button className="icon-button" aria-label="Close sources" title="Close sources" onClick={close}><Icon name="close"/></button> : null}
        </div>
      </header>

      <div className="source-toolbar">
        <button ref={uploadToggle} className="primary" disabled={blocked} aria-expanded={addingFiles} aria-controls={addingFiles ? `${panelId}-upload` : undefined}
          onClick={() => {
            setAddingFiles(!addingFiles); setLibraryChoices(null); setFiles([]);
            if (!addingFiles) requestAnimationFrame(() => fileInput.current?.focus());
          }}><Icon name="plus"/> Upload files</button>
        {!library ? <button disabled={blocked || loadingLibrary} aria-expanded={libraryChoices !== null} onClick={() => {
          setAddingFiles(false); setFiles([]);
          if (libraryChoices) setLibraryChoices(null);
          else void chooseFromLibrary();
        }}><Icon name="folder"/> {loadingLibrary ? 'Opening Library…' : 'Add from Library'}</button> : null}
      </div>
      {addingFiles ? <form id={`${panelId}-upload`} className="source-inline source-upload" onSubmit={event => {
        event.preventDefault(); if (!files.length || blocked) return;
        const data = new FormData(); files.forEach(file => data.append('files', file));
        void act('uploads', data).then(saved => { if (saved) requestAnimationFrame(() => uploadToggle.current?.focus()); });
      }}>
        <label htmlFor={fileId}>Choose documents or images</label>
        <input ref={fileInput} id={fileId} type="file" multiple disabled={blocked}
          onChange={event => setFiles(Array.from(event.target.files || []))}/>
        {list ? <p className="supporting">Up to {list.max_files} files per upload, {Math.floor(list.max_file_bytes / 1048576)} MB per file.</p> : null}
        <div className="source-row-actions">
          <button className="primary" type="submit" disabled={!files.length || blocked}>
            {files.length > 1 ? `Upload ${files.length} files` : 'Upload selected file'}
          </button>
          <button type="button" onClick={() => { setAddingFiles(false); setFiles([]); uploadToggle.current?.focus(); }}>Cancel</button>
        </div>
      </form> : null}
      {available ? <section className="source-inline library-choices" aria-label="Add from Library">
        <div className="source-section-title"><h3>Choose from Library</h3>
          <button className="icon-button" aria-label="Close Library picker" onClick={() => setLibraryChoices(null)}><Icon name="close"/></button></div>
        {available.length ? <ul className="source-list">{available.map(source => <li key={source.id}>
          <div className="source-row"><span className="source-file-text"><strong>{source.title}</strong><small>{fileDescription(source)}</small></span>
            <button disabled={blocked} aria-label={`Add ${source.title}`} onClick={() => void act(`sources/${encodeURIComponent(source.id)}/link`)}>Add</button>
          </div>
        </li>)}</ul> : <p className="supporting">No additional Library files to add.</p>}
      </section> : null}

      {error ? <p className="source-feedback" role="alert">{error}</p> : null}
      <p className={busy || notice || !list ? 'source-feedback' : 'sr-only'} role="status">
        {busy || (!list && !error) ? 'Checking sources…' : notice}</p>
      {unverified && !busy ? <p className="source-feedback">Refresh sources to confirm the last change.</p> : null}
      {visibleJobs.length ? <section className="source-inline" aria-label="Upload progress">
        <h3>Upload progress</h3>
        {visibleJobs.map(job => <div className="upload-job" key={job.id}>
          <strong>{job.filenames.join(', ')}</strong>
          <p className="supporting">{job.state === 'failed' ? 'Upload failed. Check the file list before retrying.' : job.state === 'queued' ? 'Waiting to process…' : 'Processing…'}</p>
          {job.state === 'failed' ? <div className="source-row-actions">
            <button disabled={blocked || !job.retryable} onClick={() => void act(`uploads/${encodeURIComponent(job.id)}/retry`)}>Retry upload</button>
            <button disabled={blocked} onClick={() => void act(`uploads/${encodeURIComponent(job.id)}/discard`)}>Dismiss</button>
          </div> : null}
        </div>)}
      </section> : null}

      {list ? <section className="source-catalog" aria-label={library ? 'Your files' : 'Added sources'}>
        {(documents.length > 0 || course.length > 0) ? <label className="source-search">
          <Icon name="search"/><span className="sr-only">{library ? 'Find a file' : 'Find a source'}</span>
          <input type="search" value={query} placeholder={library ? 'Find a file…' : 'Find a source…'} onChange={event => setQuery(event.target.value)}/>
        </label> : null}
        <div className="source-section-title">
          <h3>{library ? 'Your files' : 'Added sources'}</h3>
          {documents.length > 0 ? <span className="supporting">{library ? `${documents.length} ${documents.length === 1 ? 'file' : 'files'}` : `${activeCount} of ${documents.length} in use`}</span> : null}
        </div>
        {library ? <p className="source-catalog-hint">To use a file in a notebook, open its Sources and choose <strong>Add from Library</strong>.</p> : null}
        {documents.length === 0 ? <div className="source-empty">
          <strong>{library ? 'No files yet' : 'No added sources yet'}</strong>
          <p>{library ? 'Upload a file, or attach it in chat, to save it here.' : 'Upload a file or choose one from your Library.'}</p>
        </div> : documents.some(matches) ? <ul className="source-list">{documents.filter(matches).map(sourceRow)}</ul>
          : <p className="source-empty">No {library ? 'files' : 'added sources'} match your search.</p>}
        {course.length > 0 ? <details className="source-course" open={filter ? true : undefined}>
          <summary>Course materials <span className="supporting">{course.length}</span></summary>
          <p className="source-catalog-hint">Official lecture notes and readings are used for relevant Lecture Help questions.</p>
          {course.some(matches) ? <ul className="source-list">{course.filter(matches).map(sourceRow)}</ul> : <p className="supporting">No course materials match your search.</p>}
        </details> : null}
      </section> : null}
    </section> : null}
  </>;
}
