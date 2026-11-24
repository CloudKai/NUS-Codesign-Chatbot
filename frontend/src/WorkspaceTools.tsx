/** Notebook actions and preferences over the existing authenticated workspace. */
import { useEffect, useImperativeHandle, useRef, useState, type Ref, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { Icon } from './Icon';
import { ApiError, currentSession, get, type NotebookSettings, type Preferences, type Session } from './api';

export interface WorkspaceActions {
  promptNotebook: () => void;
  createChat: (parentNotebookId?: string) => void;
}

/** Align each setting's label and control, then stack them on narrow screens. */
function SettingsRow({ label, description, htmlFor, children }: {
  label: string; description?: string; htmlFor?: string; children: ReactNode;
}) {
  return <div className="settings-row">
    <div>{htmlFor ? <label htmlFor={htmlFor}>{label}</label> : <strong>{label}</strong>}
      {description ? <p className="supporting">{description}</p> : null}
    </div>
    <div className="settings-control">{children}</div>
  </div>;
}

/** Preserve native radio keyboard behavior within the segmented settings controls. */
function Segmented<T extends string>({ label, value, options, disabled, change }: {
  label: string; value: T; options: ReadonlyArray<{ value: T; label: string }>;
  disabled: boolean; change: (value: T) => void;
}) {
  return <fieldset className="settings-segmented" disabled={disabled}>
    <legend className="sr-only">{label}</legend>
    {options.map(option => <label key={option.value}>
      <input className="sr-only" type="radio" name={label} checked={option.value === value}
        value={option.value} onChange={() => change(option.value)}/>
      <span>{option.label}</span>
    </label>)}
  </fieldset>;
}

/** Keep tools local to the verified owner; reconcile writes without replaying them. */
export function WorkspaceTools({ session, thread, disabled, changed, expired, blocked, themeHost, settingsHost, ref,
  openSettings, closeSettings, onPreferences, initialPreferences }: {
  themeHost: HTMLDivElement | null; settingsHost: HTMLDivElement | null; ref: Ref<WorkspaceActions>;
  session: Session; thread?: string; disabled: boolean;
  changed: (created?: string) => Promise<void>; expired: () => void; blocked: (value: boolean) => void;
  openSettings: () => void; closeSettings: () => void; onPreferences: (value: Preferences) => void;
  initialPreferences: Preferences | null;
}) {
  const owner = session.owner_id;
  const createDialog = useRef<HTMLDialogElement>(null);
  const createName = useRef<HTMLInputElement>(null);
  const [settings, setSettings] = useState<NotebookSettings | null>(null);
  const [prefs, setPrefs] = useState<Preferences | null>(initialPreferences);
  const [displayName, setDisplayName] = useState(initialPreferences?.display_name ?? '');
  const initialLoad = useRef(true);
  const appearance = prefs?.appearance ?? 'System';
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
  const heading = useRef<HTMLHeadingElement>(null);
  const base = thread ? `/api/v1/reader/threads/${encodeURIComponent(thread)}` : '';

  async function verify() {
    const session = await currentSession(control.current.signal);
    if (!active.current) throw new Error('View closed');
    if (session.owner_id !== owner) { expired(); throw new Error('Owner changed'); }
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
    setPrefs(prefs);
    onPreferences(prefs);
    setDisplayName(prefs.display_name);
    document.documentElement.dataset.appearance = prefs.appearance;
    setSettings(detail);
    setName(detail?.notebook.name || '');
  }
  useEffect(() => {
    active.current = true;
    if (initialPreferences?.owner_id === owner) {
      document.documentElement.dataset.appearance = initialPreferences.appearance;
    }
    return () => {
      active.current = false; epoch.current++; control.current.abort();
      delete document.documentElement.dataset.appearance;
    };
  }, []);
  useEffect(() => {
    let stale = false;
    setSettings(null); setConfirm(false); setError('');
    // Only the initial, already owner-verified bootstrap replaces the redundant
    // preference-only load. Later notebook changes and mutations revalidate normally.
    const useBootstrap = initialLoad.current && !thread && initialPreferences?.owner_id === owner;
    initialLoad.current = false;
    if (useBootstrap) return;
    void load().catch(() => { if (active.current && !stale) setError('Could not load preferences. Refresh workspace to try again.'); });
    return () => { stale = true; };
  }, [thread]);
  useEffect(() => { blocked(busy || uncertain); }, [busy, uncertain]);
  useEffect(() => { if (settingsHost) heading.current?.focus({ preventScroll: true }); }, [settingsHost]);

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
      if (creating && response.ok) {
        const result: NotebookSettings = await response.json();
        if (result.owner_id !== owner || !result.notebook.id) throw new Error('Invalid created workspace');
        created = result.notebook.id;
      }
      // No write is replayed. Even a rejected or lost response is followed by canonical reads.
      if (!creating && !route.endsWith('/remove')) await load();
      await changed(created);
      if (active.current) {
        setUncertain(false); setConfirm(false);
        if (response.ok && creating) createDialog.current?.close();
        setError(response.ok ? 'Changes saved.' : 'That change was unavailable. Saved workspace refreshed.');
      }
    } catch { if (active.current) setError('Could not verify the change. Refresh workspace before continuing. A new chat or notebook may already exist. Check the sidebar before trying again.'); }
    finally { lock.current = false; if (active.current) setBusy(false); }
  }
  function updatePreferences(patch: Partial<Omit<Preferences, 'owner_id'>>) {
    return write('/api/v1/reader/preferences', patch);
  }

  const locked = disabled || busy || uncertain;
  useImperativeHandle(ref, () => ({
    promptNotebook() {
      if (locked || createDialog.current?.open) return;
      setNewName('');
      setError('');
      createDialog.current?.showModal();
      createName.current?.focus();
    },
    createChat(parentNotebookId) {
      void write('/api/v1/reader/threads', { kind: 'chat', parent_notebook_id: parentNotebookId }, true);
    },
  }));
  const entryName = settings?.notebook.kind === 'chat' ? 'chat' : 'notebook';
  const dark = appearance === 'Dark' || (appearance === 'System' && window.matchMedia('(prefers-color-scheme: dark)').matches);
  return <section className="workspace-tools" aria-label="Workspace actions">
    {themeHost ? createPortal(<button className="theme-toggle" aria-label={dark ? 'Switch to day mode' : 'Switch to night mode'} title={dark ? 'Switch to day mode' : 'Switch to night mode'} disabled={locked} onClick={() => void updatePreferences({ appearance: dark ? 'Light' : 'Dark' })}><Icon name={dark ? 'sun' : 'moon'}/></button>, themeHost) : null}
    {createPortal(<dialog ref={createDialog} className="course-dialog notebook-dialog" aria-labelledby="new-notebook-heading" aria-describedby="new-notebook-description"
      onKeyDown={event => { if (event.key === 'Escape') event.stopPropagation(); }}
      onCancel={event => { if (busy) event.preventDefault(); }}>
      <h2 id="new-notebook-heading">Create a notebook</h2>
      <p id="new-notebook-description">Group your project chats and shared sources in one folder.</p>
      <form onSubmit={event => {
        event.preventDefault();
        if (newName.trim()) void write('/api/v1/reader/threads', { name: newName.trim() }, true);
      }}>
        <label htmlFor="new-notebook-name">Notebook name</label>
        <input ref={createName} id="new-notebook-name" maxLength={120} placeholder="e.g. Campus wellbeing" value={newName} onChange={event => setNewName(event.target.value)}/>
        {error ? <p role={uncertain ? 'alert' : 'status'}>{error}</p> : null}
        <div className="notebook-dialog-actions">
          {uncertain ? <button type="button" disabled={busy} onClick={() => void refresh()}>Refresh workspace</button> : null}
          <button type="button" disabled={busy} onClick={() => createDialog.current?.close()}>Cancel</button>
          <button className="primary" disabled={locked || !newName.trim()} type="submit">{busy ? 'Creating…' : 'Create notebook'}</button>
        </div>
      </form>
    </dialog>, document.body)}
    <button aria-current={settingsHost ? 'page' : undefined} onClick={openSettings}><Icon name="settings"/> Settings</button>
    {settingsHost ? createPortal(<div className="settings-page">
      <header className="settings-heading">
        <h1 ref={heading} tabIndex={-1}>Settings</h1>
        <button onClick={() => { setConfirm(false); closeSettings(); }}>Back to chat</button>
      </header>
      <p className="supporting">Preferences are saved to your workspace.</p>
      {busy || error ? <div className="settings-status" role={uncertain && !busy ? 'alert' : 'status'}>
        {busy ? 'Checking saved workspace…' : error}
        {uncertain && !busy ? <button onClick={() => void refresh()}>Refresh workspace</button> : null}
      </div> : null}
      <section className="settings-group">
        <h2>Profile</h2>
        <form onSubmit={event => { event.preventDefault(); void updatePreferences({ display_name: displayName.trim() }); }}>
          <SettingsRow label="Display name" htmlFor="workspace-display-name" description="Shown in Co-design. Leave blank to use your account name.">
            <div className="settings-inline">
              <input id="workspace-display-name" maxLength={80} placeholder={session.display_name} value={displayName} onChange={event => setDisplayName(event.target.value)}/>
              <button disabled={locked || !prefs || displayName.trim() === prefs.display_name}>Save</button>
            </div>
          </SettingsRow>
        </form>
      </section>
      <section className="settings-group">
        <h2>Appearance</h2>
        <SettingsRow label="Theme">
          <Segmented<Preferences['appearance']> label="Theme" value={appearance} disabled={locked || !prefs}
            options={[{ value: 'Dark', label: 'Dark' }, { value: 'Light', label: 'Light' }, { value: 'System', label: 'System' }]}
            change={value => void updatePreferences({ appearance: value })}/>
        </SettingsRow>
      </section>
      <section className="settings-group">
        <h2>Learning</h2>
        <SettingsRow label="Default mode for new chats">
          <Segmented<Preferences['default_mode']> label="Default mode" value={prefs?.default_mode ?? 'lecture'} disabled={locked || !prefs}
            options={[{ value: 'project', label: 'Design coaching' }, { value: 'lecture', label: 'Lecture help' }]}
            change={value => void updatePreferences({ default_mode: value })}/>
        </SettingsRow>
        <SettingsRow label="Starter prompts" htmlFor="workspace-starters" description="Show suggestions in an empty conversation.">
          <input className="settings-switch" id="workspace-starters" type="checkbox" role="switch" checked={prefs?.starter_prompts ?? true}
            disabled={locked || !prefs} onChange={event => void updatePreferences({ starter_prompts: event.target.checked })}/>
        </SettingsRow>
        {settings ? <>
          <SettingsRow label="Response language"><span>English</span></SettingsRow>
          <SettingsRow label="Model"><span>{settings.chat_model_label || 'Course coach'}</span></SettingsRow>
        </> : null}
      </section>
      {settings ? <section className="settings-group">
        <h2>{entryName === 'chat' ? 'Current chat' : 'Current notebook'}</h2>
          <form onSubmit={event => { event.preventDefault(); void write(`${base}/settings`, { name: name.trim() }); }}>
            <SettingsRow label={entryName === 'chat' ? 'Chat name' : 'Notebook name'} htmlFor="rename-notebook">
              <div className="settings-inline">
                <input id="rename-notebook" maxLength={120} value={name} onChange={event => setName(event.target.value)}/>
                <button disabled={locked || !name.trim() || name.trim() === settings.notebook.name}>Save</button>
              </div>
            </SettingsRow>
          </form>
          <form className="settings-assignment" onSubmit={event => {
            event.preventDefault();
            const data = new FormData(event.currentTarget);
            void write(`${base}/settings`, { assignment: { ...settings.assignment, title: String(data.get('title')), brief: String(data.get('brief')) } });
          }} key={`${thread}:${JSON.stringify(settings.assignment)}`}>
            <label htmlFor="assignment-title">Assignment title</label><input id="assignment-title" name="title" maxLength={4000} defaultValue={settings.assignment.title || ''}/>
            <label htmlFor="assignment-brief">Assignment context</label><textarea id="assignment-brief" name="brief" maxLength={4000} defaultValue={settings.assignment.brief || ''}/>
            <button disabled={locked}>Save assignment context</button>
          </form>
          <SettingsRow label={`Delete ${entryName}`}>
            <button disabled={locked} onClick={() => setConfirm(value => !value)}>{confirm ? 'Cancel deletion' : `Delete ${entryName}…`}</button>
          </SettingsRow>
          {confirm ? <div className="remove-confirm">
            <p>Delete “{settings.notebook.name}” and its conversation, sources, and feedback?</p>
            {entryName === 'notebook' ? <p>Any chats organized here will return to Chats.</p> : null}
            <button disabled={locked} onClick={() => void write(`${base}/remove`, { confirmed: true })}>Confirm delete {entryName}</button>
          </div> : null}
      </section> : null}
    </div>, settingsHost) : null}
    <button className="refresh-workspace icon-button" aria-label="Refresh workspace" title="Refresh workspace" disabled={busy} onClick={() => void refresh()}><Icon name="refresh"/></button>
    {busy && !settingsHost ? <p role="status">Checking saved workspace…</p> : null}
    {error && !settingsHost ? <p role={uncertain ? 'alert' : 'status'}>{error}</p> : null}
  </section>;
}
