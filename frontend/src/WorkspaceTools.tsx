/** Notebook actions and preferences over the existing authenticated workspace. */
import { useEffect, useImperativeHandle, useRef, useState, type Ref, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { useQueryClient } from '@tanstack/react-query';
import { Icon } from './Icon';
import { ApiError, currentSession, type Preferences, type Session } from './api';
import { createThread, removeThread } from './api/client';
import { queryKeys } from './api/queryKeys';
import { reconcileNotebooks, withEntry, withoutEntry } from './api/workspaceNotebooks';
import { useNotebookSettings, usePreferences, useSavePreferences } from './api/workspaceSettings';

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
  const queryClient = useQueryClient();
  const prefsQuery = usePreferences(owner);
  const settingsQuery = useNotebookSettings(owner, thread);
  const savePreferences = useSavePreferences(owner);
  const prefs = prefsQuery.data ?? null;
  const settings = settingsQuery.data ?? null;
  const [displayName, setDisplayName] = useState(initialPreferences?.display_name ?? '');
  const appearance = prefs?.appearance ?? 'System';
  const [newName, setNewName] = useState('');
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [error, setError] = useState('');
  const active = useRef(true);
  const lock = useRef(false);
  const control = useRef(new AbortController());
  const heading = useRef<HTMLHeadingElement>(null);

  async function verify() {
    const session = await currentSession(control.current.signal);
    if (!active.current) throw new Error('View closed');
    if (session.owner_id !== owner) { expired(); throw new Error('Owner changed'); }
  }

  useEffect(() => {
    active.current = true;
    if (initialPreferences?.owner_id === owner) {
      document.documentElement.dataset.appearance = initialPreferences.appearance;
    }
    return () => {
      active.current = false; control.current.abort();
      delete document.documentElement.dataset.appearance;
    };
  }, []);
  useEffect(() => {
    if (!prefs) return;
    onPreferences(prefs);
    setDisplayName(prefs.display_name);
    document.documentElement.dataset.appearance = prefs.appearance;
  }, [prefs]);
  useEffect(() => {
    // A notebook change resets local form state; the Query resource provides the data.
    setError('');
  }, [thread]);
  useEffect(() => {
    if (active.current && (prefsQuery.isError || (thread && settingsQuery.isError))) {
      setError('Could not load preferences. Refresh workspace to try again.');
    }
  }, [prefsQuery.isError, settingsQuery.isError, thread]);
  useEffect(() => { blocked(busy || uncertain); }, [busy, uncertain]);
  useEffect(() => { if (settingsHost) heading.current?.focus({ preventScroll: true }); }, [settingsHost]);

  async function refresh() {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError('');
    try {
      await verify();
      const refetches: Promise<{ isError: boolean }>[] = [prefsQuery.refetch()];
      if (thread) refetches.push(settingsQuery.refetch());
      const results = await Promise.all(refetches);
      await verify();
      if (results.some(result => result.isError)) throw new Error('Refresh failed');
      await changed();
      if (active.current) { setUncertain(false); setError('Workspace refreshed.'); }
    }
    catch { if (active.current) setError('Could not verify saved workspace. Refresh before another change.'); }
    finally { lock.current = false; if (active.current) setBusy(false); }
  }

  /** Shared write frame: never replay a write; reconcile through confirmed owner-fenced reads. */
  function writeFrame(action: () => Promise<unknown>) {
    return (async () => {
      if (lock.current || disabled || uncertain) return;
      lock.current = true; setBusy(true); setUncertain(true); setError('');
      try {
        await verify();
        await action();
        await verify();
        if (active.current) {
          setUncertain(false);
          setError('Changes saved.');
        }
      } catch (error) {
        if (error instanceof ApiError && [401, 403].includes(error.status)) { expired(); return; }
        if (active.current) setError('Could not verify the change. Refresh workspace before continuing. A new chat or notebook may already exist. Check the sidebar before trying again.');
      } finally { lock.current = false; if (active.current) setBusy(false); }
    })();
  }

  function updatePreferences(patch: Partial<Omit<Preferences, 'owner_id'>>) {
    return writeFrame(() => savePreferences.mutateAsync({ patch, signal: control.current.signal }));
  }

  /** Create and confirmed delete run generated contracts; ambiguous outcomes reconcile through an explicit refresh. */
  async function write(kind: 'create' | 'remove', body: object, creating = false) {
    if (lock.current || disabled || uncertain) return;
    lock.current = true; setBusy(true); setUncertain(true); setError('');
    let created: string | undefined;
    try {
      await verify();
      if (kind === 'create') {
        const result = await createThread(body as { name: string } | { kind: 'chat'; parent_notebook_id?: string | null },
          control.current.signal);
        await verify();
        if (result.owner_id !== owner || !result.notebook.id) throw new Error('Invalid created workspace');
        created = result.notebook.id;
        await reconcileNotebooks(queryClient, owner, list => withEntry(list, result.notebook));
      } else if (thread) {
        const removed = await removeThread(thread, control.current.signal);
        await verify();
        if (removed.owner_id !== owner) throw new Error('Invalid removed workspace');
        // The removed notebook's settings resource no longer exists.
        queryClient.removeQueries({ queryKey: queryKeys.notebookSettings(owner, thread) });
        await reconcileNotebooks(queryClient, owner, list => withoutEntry(list, thread));
      }
      await changed(created);
      if (active.current) {
        setUncertain(false);
        if (creating) createDialog.current?.close();
        setError('Changes saved.');
      }
    } catch (error) {
      if (error instanceof ApiError && [401, 403].includes(error.status)) { expired(); return; }
      if (error instanceof ApiError) {
        try { await changed(created); } catch { /* The sidebar refresh failure is reported by its caller. */ }
        if (active.current) { setUncertain(false); setError('That change was unavailable. Saved workspace refreshed.'); }
        return;
      }
      if (active.current) setError('Could not verify the change. Refresh workspace before continuing. A new chat or notebook may already exist. Check the sidebar before trying again.');
    } finally { lock.current = false; if (active.current) setBusy(false); }
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
      void write('create', { kind: 'chat', parent_notebook_id: parentNotebookId }, true);
    },
  }));
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
        if (newName.trim()) void write('create', { name: newName.trim() }, true);
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
        <button onClick={() => closeSettings()}>Back to chat</button>
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
          <Segmented<Preferences['default_mode']> label="Default mode" value={prefs?.default_mode ?? 'improve'} disabled={locked || !prefs}
            options={[{ value: 'project', label: 'Design coaching' }, { value: 'improve', label: 'Improve my design' }]}
            change={value => void updatePreferences({ default_mode: value })}/>
        </SettingsRow>
        <SettingsRow label="Starter prompts" htmlFor="workspace-starters" description="Show suggestions in an empty conversation.">
          <input className="settings-switch" id="workspace-starters" type="checkbox" role="switch" checked={prefs?.starter_prompts ?? true}
            disabled={locked || !prefs} onChange={event => void updatePreferences({ starter_prompts: event.target.checked })}/>
        </SettingsRow>
        {settings ? <SettingsRow label="Response language"><span>English</span></SettingsRow> : null}
      </section>
    </div>, settingsHost) : null}
    <button className="refresh-workspace icon-button" aria-label="Refresh workspace" title="Refresh workspace" disabled={busy} onClick={() => void refresh()}><Icon name="refresh"/></button>
    {busy && !settingsHost ? <p role="status">Checking saved workspace…</p> : null}
    {error && !settingsHost ? <p role={uncertain ? 'alert' : 'status'}>{error}</p> : null}
  </section>;
}
