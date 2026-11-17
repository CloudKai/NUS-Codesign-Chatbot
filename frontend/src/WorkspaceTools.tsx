/** Notebook actions and preferences over the existing authenticated workspace. */
import { useEffect, useRef, useState } from 'react';
import { ApiError, currentSession, get, type NotebookSettings, type Preferences } from './api';

/** Keep tools local to the verified owner; reconcile writes without replaying them. */
export function WorkspaceTools({ owner, thread, disabled, changed, expired, blocked }: {
  owner: string; thread?: string; disabled: boolean;
  changed: (created?: string) => Promise<void>; expired: () => void; blocked: (value: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const [settings, setSettings] = useState<NotebookSettings | null>(null);
  const [appearance, setAppearance] = useState<Preferences['appearance']>('System');
  const [name, setName] = useState('');
  const [newName, setNewName] = useState('');
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [error, setError] = useState('');
  const active = useRef(true);
  const lock = useRef(false);
  const epoch = useRef(0);
  const control = useRef(new AbortController());
  const trigger = useRef<HTMLButtonElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const base = thread ? `/api/v1/reader/threads/${encodeURIComponent(thread)}` : '';

  async function verify() {
    const session = await currentSession(control.current.signal);
    if (!active.current) throw new Error('View closed');
    if (session.owner_id !== owner) { expired(); throw new Error('Owner changed'); }
  }
  function applyTheme(value: Preferences['appearance']) {
    setAppearance(value);
    document.documentElement.dataset.appearance = value;
  }
  async function load() {
    const token = ++epoch.current;
    await verify();
    const [prefs, detail] = await Promise.all([
      get<Preferences>('/api/v1/reader/preferences', control.current.signal),
      thread ? get<NotebookSettings>(`${base}/settings`, control.current.signal).catch(error => {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }) : Promise.resolve(null),
    ]);
    await verify();
    if (token !== epoch.current) throw new Error('View changed');
    if (prefs.owner_id !== owner || (detail && (detail.owner_id !== owner || detail.notebook.id !== thread))) throw new Error('Owner changed');
    applyTheme(prefs.appearance); setSettings(detail); setName(detail?.notebook.name || '');
  }
  useEffect(() => {
    active.current = true;
    return () => { active.current = false; epoch.current++; control.current.abort(); delete document.documentElement.dataset.appearance; };
  }, []);
  useEffect(() => {
    let stale = false;
    setSettings(null); setConfirm(false); setOpen(false); setError('');
    void load().catch(() => { if (active.current && !stale) setError('Could not load preferences. Refresh workspace to try again.'); });
    return () => { stale = true; };
  }, [thread]);
  useEffect(() => { blocked(busy || uncertain); }, [busy, uncertain]);
  useEffect(() => { if (open) heading.current?.focus({ preventScroll: true }); }, [open]);

  async function refresh() {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError('');
    try { await changed(); await load(); if (active.current) { setUncertain(false); setError('Workspace refreshed.'); } }
    catch { if (active.current) setError('Could not verify saved workspace. Refresh before another change.'); }
    finally { lock.current = false; if (active.current) setBusy(false); }
  }
  async function write(route: string, body: object, creating = false) {
    if (lock.current || disabled || uncertain) return;
    lock.current = true; setBusy(true); setUncertain(true); setError('');
    let created: string | undefined;
    try {
      await verify();
      const response = await fetch(route, { method: 'POST', credentials: 'same-origin', cache: 'no-store',
        signal: control.current.signal, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      await verify();
      if ([401, 403].includes(response.status)) { expired(); return; }
      if (creating && response.ok) created = ((await response.json()) as NotebookSettings).notebook.id;
      // No write is replayed. Even a rejected or lost response is followed by canonical reads.
      if (!creating && !route.endsWith('/remove')) await load();
      await changed(created);
      if (active.current) {
        setUncertain(false); setConfirm(false);
        if (response.ok && creating) setNewName('');
        setError(response.ok ? 'Changes saved.' : 'That change was unavailable. Saved workspace refreshed.');
      }
    } catch { if (active.current) setError('Could not verify the change. Refresh workspace before continuing. A new notebook may already exist; inspect the list before creating again.'); }
    finally { lock.current = false; if (active.current) setBusy(false); }
  }
  async function download() {
    if (!thread) return;
    try {
      await verify();
      const response = await fetch(`${base}/transcript.txt`, { credentials: 'same-origin', cache: 'no-store', signal: control.current.signal });
      if (!response.ok) throw new ApiError(response.status);
      const blob = await response.blob(); await verify();
      const url = URL.createObjectURL(blob); const link = document.createElement('a');
      link.href = url; link.download = `${settings?.notebook.name || 'Notebook'}-transcript.txt`; link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch { if (active.current) setError('Transcript unavailable. Refresh the workspace and try again.'); }
  }
  const locked = disabled || busy || uncertain;
  return <section className="workspace-tools" aria-label="Workspace actions">
    <form className="new-notebook" onSubmit={event => { event.preventDefault(); void write('/api/v1/reader/threads', { name: newName }, true); }}>
      <label htmlFor="new-notebook-name">New notebook</label>
      <input id="new-notebook-name" maxLength={120} placeholder="Notebook name" value={newName} onChange={event => setNewName(event.target.value)}/>
      <button disabled={locked || !newName.trim()} type="submit">Create notebook</button>
    </form>
    <button ref={trigger} aria-expanded={open} aria-controls="workspace-preferences" onClick={() => { setOpen(value => !value); setConfirm(false); }}>Preferences & notebook</button>
    {open ? <div id="workspace-preferences" className="workspace-preferences" onKeyDown={event => {
      if (event.key === 'Escape') { setOpen(false); trigger.current?.focus(); }
    }}>
      <div className="tool-heading"><h2 ref={heading} tabIndex={-1}>Preferences</h2><button onClick={() => { setOpen(false); trigger.current?.focus(); }}>Close preferences</button></div>
      <label htmlFor="appearance">Appearance</label>
      <select id="appearance" value={appearance} disabled={locked} onChange={event => void write('/api/v1/reader/preferences', { appearance: event.target.value })}>
        {['System', 'Light', 'Dark'].map(value => <option key={value}>{value}</option>)}
      </select>
      {settings ? <>
        <form onSubmit={event => { event.preventDefault(); void write(`${base}/settings`, { name }); }}>
          <label htmlFor="rename-notebook">Notebook name</label><input id="rename-notebook" maxLength={120} value={name} onChange={event => setName(event.target.value)}/>
          <button disabled={locked || !name.trim()}>Rename notebook</button>
        </form>
        <p className="supporting">Response changes apply to future answers. Evidence and quotations keep their original wording.</p>
        <label htmlFor="response-detail">Coaching style</label>
        <select id="response-detail" value={settings.response_detail} disabled={locked} onChange={event => void write(`${base}/settings`, { response_detail: event.target.value })}>
          <option value="short">Guide</option><option value="long">Free</option>
        </select>
        <label htmlFor="response-language">Response language</label>
        <select id="response-language" value={settings.response_language} disabled={locked} onChange={event => void write(`${base}/settings`, { response_language: event.target.value })}>
          {Array.from(new Set(['English', '中文', 'Bahasa Melayu', 'தமிழ்', settings.response_language])).map(value => <option key={value}>{value}</option>)}
        </select>
        <label htmlFor="model">Model</label><select id="model" disabled={locked} value={settings.selected_model} onChange={event => void write(`${base}/settings`, { selected_model: event.target.value })}>
          {settings.models.map(model => <option key={model.id} value={model.id}>{model.label}</option>)}
        </select>
        <label htmlFor="reasoning">Reasoning effort</label><select id="reasoning" disabled={locked} value={settings.reasoning_effort || ''} onChange={event => void write(`${base}/settings`, { reasoning_effort: event.target.value })}>
          {settings.models.find(model => model.id === settings.selected_model)?.reasoning_efforts.map(value => <option key={value}>{value}</option>)}
        </select>
        <form onSubmit={event => {
          event.preventDefault(); const data = new FormData(event.currentTarget);
          void write(`${base}/settings`, { assignment: { ...settings.assignment, title: String(data.get('title')), brief: String(data.get('brief')) } });
        }} key={`${thread}:${JSON.stringify(settings.assignment)}`}>
          <label htmlFor="assignment-title">Assignment title</label><input id="assignment-title" name="title" maxLength={4000} defaultValue={settings.assignment.title || ''}/>
          <label htmlFor="assignment-brief">Assignment context</label><textarea id="assignment-brief" name="brief" maxLength={4000} defaultValue={settings.assignment.brief || ''}/>
          <button disabled={locked}>Save assignment context</button>
        </form>
        <button onClick={() => void download()}>Download transcript</button>
        {!confirm ? <button disabled={locked} onClick={() => setConfirm(true)}>Delete notebook…</button> : <div className="remove-confirm">
          <p>Delete “{settings.notebook.name}” and its prompts, responses, sources and feedback? This cannot be undone.</p>
          <button disabled={locked} onClick={() => setConfirm(false)}>Cancel deletion</button>
          <button disabled={locked} onClick={() => void write(`${base}/remove`, { confirmed: true })}>Confirm delete notebook</button>
        </div>}
      </> : <p className="supporting">Choose a notebook for response settings and transcript actions.</p>}
      <p className="supporting">Folder organization is unavailable. Use notebooks to organize your work. Additional tools remain in Streamlit.</p>
    </div> : null}
    <button disabled={busy} onClick={() => void refresh()}>Refresh workspace</button>
    {busy ? <p role="status">Checking saved workspace…</p> : null}
    {error ? <p role={uncertain ? 'alert' : 'status'}>{error}</p> : null}
  </section>;
}
