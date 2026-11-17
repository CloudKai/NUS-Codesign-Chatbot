/** Notebook-scoped source work independent of the mounted conversation and composer. */
import { useEffect, useRef, useState } from 'react';
import { ApiError, currentSession, get } from './api';

interface Source { id: string; title: string; selected: boolean; locked: boolean; kind: string; size: number }
interface SourceList { owner_id: string; thread_id: string; sources: Source[]; max_files: number; max_file_bytes: number }
interface Job { id: string; filenames: string[]; state: 'queued' | 'processing' | 'saved' | 'failed'; retryable: boolean }
interface Jobs { owner_id: string; thread_id: string; jobs: Job[] }
interface Detail { source: Source; text: string; truncated: boolean }

/** Show safe source controls while keeping drafts, transcript, and source authority separate. */
export function Sources({ owner, thread, expired, uncertain, opened, disabled }: {
  disabled: boolean; owner: string; thread: string; expired: () => void; uncertain: (value: boolean) => void; opened: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [list, setList] = useState<SourceList | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [removing, setRemoving] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [unverified, setUnverified] = useState(false);
  const [notice, setNotice] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const active = useRef(true);
  const lock = useRef(false);
  const controller = useRef(new AbortController());
  const trigger = useRef<HTMLButtonElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const detailHeading = useRef<HTMLHeadingElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const scroll = useRef(0);
  const sequence = useRef(0);
  const path = `/api/v1/reader/threads/${encodeURIComponent(thread)}`;

  async function verify() {
    const session = await currentSession(controller.current.signal);
    if (!active.current) throw new Error('Closed');
    if (session.owner_id !== owner) { expired(); throw new Error('Session changed'); }
  }

  function failure(error: unknown) {
    if (!active.current) return;
    if (error instanceof ApiError && [401, 403].includes(error.status)) expired();
    else setError('Could not verify sources. Refresh sources when connected. Your chat draft is kept.');
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
    setDetail(value => value && next.sources.some(source => source.id === value.source.id) ? value : null);
    setUnverified(false); uncertain(false); setError('');
  }

  async function act(route: string, body?: object | FormData) {
    if (lock.current || unverified || disabled) return;
    lock.current = true; setBusy(true); setError('');
    setUnverified(true); uncertain(true);
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
      setNotice(response.ok ? route === 'uploads' ? 'Upload accepted. Processing continues if you leave this view.' : 'Source action checked.'
        : response.status === 429 ? 'Upload allowance is full or uploads are busy. Wait, or dismiss failed uploads and choose fewer or smaller files.'
        : response.status === 413 || response.status === 400 ? 'Files exceed the upload limits. Choose fewer or smaller files.'
        : 'That source action is unavailable or changed. Saved sources refreshed.');
      await refresh();
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
      setDetail(next); setRemoving(''); heading.current?.focus({ preventScroll: true });
    } catch (error) { failure(error); }
    finally { lock.current = false; if (active.current) setBusy(false); }
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
    setOpen(false); setDetail(null); setRemoving(''); setFiles([]);
    trigger.current?.focus({ preventScroll: true }); window.scrollTo(0, scroll.current);
  }

  useEffect(() => {
    active.current = true;
    void refresh().catch(failure);
    return () => { active.current = false; sequence.current += 1; controller.current.abort(); };
  }, []);
  useEffect(() => {
    if (!open) return;
    heading.current?.focus({ preventScroll: true });
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') close(); };
    window.addEventListener('keydown', escape);
    return () => window.removeEventListener('keydown', escape);
  }, [open]);
  useEffect(() => { if (detail) detailHeading.current?.focus(); }, [detail]);
  useEffect(() => {
    if (!open || unverified || busy || !jobs.some(job => ['queued', 'processing'].includes(job.state))) return;
    const timer = window.setTimeout(() => { void refresh().catch(failure); }, 1200);
    return () => window.clearTimeout(timer);
  }, [open, jobs, unverified, busy]);

  return <>
    <button ref={trigger} aria-expanded={open} aria-controls="source-panel" onClick={() => {
      scroll.current = window.scrollY; opened(); setOpen(true); if (!lock.current) void refresh().catch(failure);
    }}>Sources{list ? ` · ${list.sources.filter(source => source.selected).length} selected` : ''}</button>
    {open ? <aside id="source-panel" className="evidence source-panel" aria-label="Notebook sources">
      <div className="evidence-heading"><h3 ref={heading} tabIndex={-1}>Sources</h3><button onClick={close}>Return to chat</button></div>
      <p className="supporting">Changes apply to future answers. Answers already in progress may still cite their original sources. Removing a source keeps saved answers and citation labels, but removes its download.</p>
      <button disabled={busy} onClick={() => { setBusy(true); void refresh().catch(failure).finally(() => { if (active.current) setBusy(false); }); }}>Refresh sources</button>
      {error ? <p role="alert">{error}</p> : null}
      <p role="status">{busy ? 'Checking sources…' : notice}</p>
      {unverified ? <p className="supporting">Source changes and new questions pause until a successful refresh.</p> : null}
      <form className="source-upload" onSubmit={event => {
        event.preventDefault(); if (!files.length || busy || unverified || disabled) return;
        const data = new FormData(); files.forEach(file => data.append('files', file)); void act('uploads', data);
      }}>
        <label htmlFor="source-files">Add files to this notebook</label>
        <input ref={fileInput} id="source-files" type="file" multiple disabled={busy || unverified || disabled}
          onChange={event => setFiles(Array.from(event.target.files || []))}/>
        <p className="supporting">{list ? `Up to ${list.max_files} files per batch, ${Math.floor(list.max_file_bytes / 1048576)} MB per file. ` : ''}Documents, text and images can be stored; extracted text is available where supported.</p>
        <button type="submit" disabled={!files.length || busy || unverified || disabled}>Upload files</button>
      </form>
      {jobs.length ? <section aria-label="Upload progress" className="upload-jobs"><h4>Upload progress</h4>
        <p className="supporting">Retry is available for up to 5 minutes after first failure, with 3 attempts total. Check available sources before retrying; earlier files in a failed batch may already be saved. Receipts expire and clear on server restart; saved sources remain below.</p>
        {jobs.map(job => <div className="upload-job" key={job.id}>
          <strong>{job.filenames.join(', ')}</strong><p>{({queued: 'Queued — waiting for an upload worker…', processing: 'Processing source…', saved: 'Saved to sources', failed: 'Upload failed'})[job.state]}</p>
          {job.state === 'failed' ? <button disabled={busy || unverified || disabled || !job.retryable} onClick={() => void act(`uploads/${encodeURIComponent(job.id)}/retry`)}>Retry upload</button> : null}
          {!['queued', 'processing'].includes(job.state) ? <button disabled={busy || unverified || disabled} onClick={() => void act(`uploads/${encodeURIComponent(job.id)}/discard`)}>{job.state === 'failed' ? 'Dismiss failed upload' : 'Dismiss receipt'}</button> : null}
        </div>)}
      </section> : null}
      <h4>Available sources{list ? ` · ${list.sources.length}` : ''}</h4>
      {list?.sources.length === 0 ? <p>Add your first source to ground notebook answers.</p> : null}
      <ul className="source-list">{list?.sources.map(source => <li key={source.id}>
        <label><input type="checkbox" checked={source.selected} disabled={source.locked || busy || unverified || disabled} onChange={event => void act(`sources/${encodeURIComponent(source.id)}/select`, {selected: event.target.checked})}/>{source.title}</label>
        <p className="supporting">{source.locked ? 'Course material · always included' : `${source.kind} · ${source.size.toLocaleString()} bytes`}</p>
        <div className="source-actions"><button id={`inspect-${source.id}`} disabled={busy} onClick={() => void inspect(source)}>Inspect {source.title}</button>
          <button onClick={() => void download(source)}>Download {source.title}</button>
          {!source.locked ? <button disabled={busy || unverified || disabled} onClick={() => { setRemoving(source.id); setDetail(null); }}>Remove {source.title}</button> : null}</div>
        {removing === source.id ? <div className="remove-confirm" role="group" aria-label={`Remove ${source.title}?`}>
          <p>Remove this source from the notebook? Saved answers remain, but its original will no longer be downloadable.</p>
          <button disabled={busy || unverified || disabled} onClick={() => { void act(`sources/${encodeURIComponent(source.id)}/remove`).then(() => {
            if (active.current) { setRemoving(''); heading.current?.focus({preventScroll: true}); }
          }); }}>Confirm removal</button><button onClick={() => setRemoving('')}>Keep source</button>
        </div> : null}
      </li>)}</ul>
      {detail ? <section className="source-detail" aria-label="Extracted source text"><h4 ref={detailHeading} tabIndex={-1}>{detail.source.title}</h4>
        <button onClick={() => { const id = detail.source.id; setDetail(null); document.getElementById(`inspect-${id}`)?.focus(); }}>Close inspection</button>
        <p className="supporting">Extracted text{detail.truncated ? ' · first 24,000 characters; download for the complete source' : ''}</p>
        <pre>{detail.text || 'No extracted text is available. Download the original to inspect it.'}</pre>
      </section> : null}
    </aside> : null}
  </>;
}
