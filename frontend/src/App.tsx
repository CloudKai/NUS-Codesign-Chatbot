/** CDE2300 lecture and project companion over the shared coaching policy. */
import { useEffect, useRef, useState } from 'react';
import { useReader } from './useReader';
import { Conversation } from './Conversation';
import { ChatNavigation } from './ChatNavigation';
import { Sources } from './Sources';
import { NotebookPage } from './NotebookPage';
import { WorkspaceSearch } from './WorkspaceSearch';
import type { Preferences } from './api';
import { WorkspaceTools, type WorkspaceActions } from './WorkspaceTools';
import { Icon } from './Icon';

/** Render authentication, notebook navigation, and saved transcript reading states. */
export default function App() {
  const reader = useReader();
  const session = reader.session;
  useEffect(() => {
    if (reader.phase !== 'signed-out' && !(reader.phase === 'error' && reader.error === 'This account cannot access the student workspace.')) return;
    try {
      for (const key of Object.keys(sessionStorage)) {
        if (key.startsWith('codesign-lecture:') || key.startsWith('codesign-selected:')) sessionStorage.removeItem(key);
      }
    } catch { /* No persistent draft exists when tab storage is blocked. */ }
  }, [reader.phase, reader.error]);
  return <>
    <a className="skip-link" href="#main">Skip to saved work</a>
    {!session ? <><header className="app-header"><Brand/></header><main id="main" className="entry">
      <h1>Pick up your questions<br/>and project thinking.</h1>
      <p>Ask about lectures, develop your project, and resume saved work in your notebooks.</p>
      <p className="course-notice">Your chatbot work is never graded and has no association with your course grades. This companion is used for CDE2300. Researchers want to understand how students use it and whether it benefits learning.</p>
      {reader.phase === 'checking' ? <p role="status">Checking your session…</p> : <>
        <div className="entry-actions"><a className="primary action" href="/api/v1/auth/login">Sign in</a>
          <button onClick={() => void reader.startGuest()}>Continue as Guest</button></div>
        <p className="supporting">Guest notebooks stay with this browser.</p>
      </>}
      {new URLSearchParams(window.location.search).has('auth_error') ? <p role="alert">Sign-in was unavailable. Please try again.</p> : null}
      {reader.error ? <p role="alert">{reader.error} <button onClick={() => void reader.reload()}>Try again</button></p> : null}
    </main></> : <ReaderWorkspace key={session.owner_id} reader={reader}/>}
  </>;
}

/** Show the course identity on every entry screen. */
function Brand() {
  return <div className="brand"><a className="wordmark" href="/">CDE2300</a><span className="reader-label">Co-design</span></div>;
}

/** Keep navigation text ephemeral and reset it with the authenticated owner. */
function ReaderWorkspace({ reader }: { reader: ReturnType<typeof useReader> }) {
  const [themeHost, setThemeHost] = useState<HTMLDivElement | null>(null);
  const [helpOpen, setHelpOpen] = useState(false);
  const [view, setView] = useState<'chat' | 'notebook' | 'library' | 'search' | 'settings'>('chat');
  const [settingsReturn, setSettingsReturn] = useState<'chat' | 'notebook' | 'library' | 'search'>('chat');
  const [folderId, setFolderId] = useState<string>();
  const [settingsHost, setSettingsHost] = useState<HTMLDivElement | null>(null);
  const [preferences, setPreferences] = useState<Preferences | null>(null);
  const [onboardingRequest, setOnboardingRequest] = useState(0);
  const [search, setSearch] = useState('');
  const [activity, setActivity] = useState(false);
  const [workspaceBlocked, setWorkspaceBlocked] = useState(false);
  const [listOpen, setListOpen] = useState(() => window.innerWidth >= 1024);
  const workspaceActions = useRef<WorkspaceActions>(null);
  const [sections, setSections] = useState({ notebooks: true, chats: true });
  const setSection = (section: keyof typeof sections, open: boolean) => setSections(value => ({ ...value, [section]: open }));
  const promptNotebook = () => workspaceActions.current?.promptNotebook();
  const workspaceLocked = activity || reader.busy || workspaceBlocked;
  const closeMobileList = () => { if (window.innerWidth < 1024) setListOpen(false); };
  useEffect(() => {
    const desktop = window.matchMedia('(min-width: 1024px)');
    const syncNavigation = (event: MediaQueryListEvent) => setListOpen(event.matches);
    desktop.addEventListener('change', syncNavigation);
    return () => desktop.removeEventListener('change', syncNavigation);
  }, []);
  const toggle = useRef<HTMLButtonElement>(null);
  const railToggle = useRef<HTMLButtonElement>(null);
  const accountLink = useRef<HTMLAnchorElement>(null);
  const helpDialog = useRef<HTMLDialogElement>(null);
  function openSearch() {
    setView('search');
    closeMobileList();
    searchInput.current?.focus();
  }
  function openNavigation() {
    setListOpen(true);
    window.requestAnimationFrame(() => document.getElementById('collapse-navigation')?.focus());
  }
  function closeNavigation() {
    setListOpen(false);
    window.requestAnimationFrame(() => (window.innerWidth >= 768 ? railToggle : toggle).current?.focus());
  }
  useEffect(() => {
    if (view === 'search') searchInput.current?.focus();
  }, [view]);
  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k' && !document.querySelector('dialog:modal')) {
        event.preventDefault();
        openSearch();
      }
    };
    window.addEventListener('keydown', shortcut);
    return () => window.removeEventListener('keydown', shortcut);
  }, []);
  useEffect(() => {
    if (helpOpen && !helpDialog.current?.open) helpDialog.current?.showModal();
  }, [helpOpen]);
  const searchInput = useRef<HTMLInputElement>(null);
  const session = reader.session!;
  useEffect(() => {
    try {
      // Drafts belong to one verified owner in this tab. Replies are never stored.
      for (const key of Object.keys(sessionStorage)) {
        if (key.startsWith('codesign-lecture:') && !key.startsWith(`codesign-lecture:${session.owner_id}:`)) sessionStorage.removeItem(key);
      }
      const selected = sessionStorage.getItem(`codesign-selected:${session.owner_id}`);
      if (selected?.startsWith('folder:')) {
        const id = selected.slice('folder:'.length);
        if (reader.notebooks.some(item => item.id === id && item.kind === 'notebook')) openFolder(id);
      } else if (selected && reader.notebooks.some(item => item.id === selected)) {
        closeMobileList();
        void reader.open(selected);
      }
    } catch { /* Reading still works when browser tab storage is unavailable. */ }
  }, []);
  function startChat() {
    if (workspaceLocked) return;
    if (reader.page?.notebook.kind === 'chat' && !reader.page.notebook.parent_notebook_id && reader.page.total_count === 0) {
      setView('chat');
      closeMobileList();
      window.requestAnimationFrame(() => document.getElementById('lecture-question')?.focus({ preventScroll: true }));
    } else {
      workspaceActions.current?.createChat();
    }
  }
  function openChat(id: string) {
    setView('chat');
    setSearch('');
    closeMobileList();
    document.getElementById('main')?.focus();
    try { sessionStorage.setItem(`codesign-selected:${session.owner_id}`, id); } catch { /* Optional navigation restoration. */ }
    if (reader.page?.notebook.id !== id) void reader.open(id);
  }
  function openFolder(id: string) {
    setFolderId(id);
    setView('notebook');
    setSearch('');
    closeMobileList();
    window.requestAnimationFrame(() => document.getElementById('main')?.focus({ preventScroll: true }));
    try { sessionStorage.setItem(`codesign-selected:${session.owner_id}`, `folder:${id}`); } catch { /* Optional navigation restoration. */ }
  }
  function openLibrary() {
    setView('library');
    closeMobileList();
  }
  const folder = reader.notebooks.find(item => item.id === folderId && item.kind === 'notebook');
  const selectedChat = reader.page?.notebook;
  const parentId = selectedChat?.kind === 'notebook' ? selectedChat.id : selectedChat?.parent_notebook_id;
  const parentFolder = reader.notebooks.find(item => item.id === parentId && item.kind === 'notebook');
  const folderSettings = view === 'notebook' || (view === 'settings' && settingsReturn === 'notebook');

  return <>
    <header className="app-header">
      <button ref={toggle} className="header-menu icon-button" aria-label="Open navigation" aria-expanded={listOpen} aria-controls="notebook-list" onClick={() => listOpen ? closeNavigation() : openNavigation()}><Icon name="panel"/></button>
      <Brand/>
      <div className="header-actions">
        <button className="icon-button header-help" aria-label="How it works" title="How it works" onClick={() => setHelpOpen(true)}><Icon name="help"/></button>
        <div className="theme-control" ref={setThemeHost}/>
      </div>
    </header>
    <dialog className="course-dialog" ref={helpDialog} onClose={() => setHelpOpen(false)}>
      <h2>How does this work?</h2>
      <p>Ask about lectures in Lecture help, or work through your design project in Design coaching.</p>
      <p>Use the Thinking Path to review your progress. When the coach recommends a new stage, you decide whether to move on.</p>
      <form method="dialog"><button>Done</button></form>
    </dialog>
    <div className={`workspace ${listOpen ? 'nav-open' : 'nav-collapsed'}`}>
      {listOpen ? <button className="drawer-backdrop" aria-label="Close navigation" onClick={closeNavigation}/> : null}
      {!listOpen ? <nav className="navigation-rail" aria-label="Workspace shortcuts">
        <button ref={railToggle} className="icon-button" aria-label="Expand navigation" title="Expand navigation" onClick={openNavigation}><Icon name="panel"/></button>
        <button className="icon-button" aria-label="New Chat" title="New Chat" disabled={workspaceLocked} onClick={startChat}><Icon name="edit"/></button>
        <button className="icon-button" aria-label="Search" aria-current={view === 'search' ? 'page' : undefined} aria-keyshortcuts="Meta+K Control+K" title="Search notebooks and chats" onClick={openSearch}><Icon name="search"/></button>
        <button className="icon-button" aria-label="Library" title="Library" onClick={openLibrary}><Icon name="book"/></button>
        <button className="icon-button rail-account" aria-label="Account" title="Account" aria-controls="notebook-list" onClick={() => {
          setListOpen(true);
          window.requestAnimationFrame(() => accountLink.current?.focus());
        }}><span className="profile-avatar"><Icon name="user"/></span></button>
      </nav> : null}
      <aside onKeyDown={event => { if (event.key === 'Escape' && !event.defaultPrevented && event.currentTarget.contains(event.target as Node)) closeNavigation(); }} id="notebook-list" className={`notebooks ${listOpen ? 'list-open' : ''}`} aria-label="Your notebooks">
        <div className="notebook-heading"><span>Co-design</span>
          <button id="collapse-navigation" className="icon-button" aria-label="Collapse navigation" title="Collapse navigation" onClick={closeNavigation}><Icon name="panel"/></button></div>
        <button className="nav-new" disabled={workspaceLocked} onClick={startChat}><Icon name="edit"/> New Chat</button>
        <button className="nav-search-link" aria-current={view === 'search' ? 'page' : undefined} aria-keyshortcuts="Meta+K Control+K" onClick={openSearch}><Icon name="search"/> Search<kbd aria-hidden="true">{/Mac|iPhone|iPad/.test(navigator.platform) ? '⌘K' : 'Ctrl K'}</kbd></button>
        <button className="nav-library" aria-current={view === 'library' ? 'page' : undefined} onClick={openLibrary}><Icon name="book"/> Library</button>
        <ChatNavigation entries={reader.notebooks} currentId={view === 'chat' ? reader.page?.notebook.id : undefined}
          folderId={view === 'notebook' ? folderId : undefined} summaries={reader.chatSummaries}
          locked={workspaceLocked} sections={sections} setSection={setSection} newNotebook={promptNotebook}
          open={openChat} openFolder={openFolder} move={reader.moveChat}
          commands={{ rename: reader.renameChat, pin: reader.pinChat, remove: reader.deleteChat, share: reader.shareChat }}/>
        <WorkspaceTools ref={workspaceActions} themeHost={themeHost} settingsHost={settingsHost}
          session={session} project={folderSettings ? null : reader.project} onPreferences={setPreferences}
          openSettings={() => { if (view !== 'settings') setSettingsReturn(view); setView('settings'); closeMobileList(); }}
          closeSettings={() => { setView(settingsReturn === 'notebook' && !folder ? 'chat' : settingsReturn); document.getElementById('main')?.focus(); }}
          resetOnboarding={() => setOnboardingRequest(value => value + 1)} thread={folderSettings ? folder?.id : selectedChat?.id} disabled={activity || reader.busy}
          blocked={setWorkspaceBlocked} expired={() => void reader.reload()} changed={async created => {
            const list = await reader.refreshList();
            if (created) {
              const entry = list.notebooks.find(item => item.id === created);
              if (!entry) throw new Error('Created workspace unavailable');
              if (entry.kind === 'notebook') {
                setSection('notebooks', true);
                openFolder(created);
                return;
              }
              if (!await reader.open(created)) throw new Error('Created workspace could not open');
              setView('chat'); setSearch(''); closeMobileList();
              setSection(entry.parent_notebook_id ? 'notebooks' : 'chats', true);
              window.requestAnimationFrame(() => document.getElementById('lecture-question')?.focus({ preventScroll: true }));
              try { sessionStorage.setItem(`codesign-selected:${session.owner_id}`, created); } catch { /* Optional navigation only. */ }
            } else if (folderSettings && folderId && !list.notebooks.some(item => item.id === folderId)) {
              setFolderId(undefined);
              setSettingsReturn('chat');
              try { sessionStorage.removeItem(`codesign-selected:${session.owner_id}`); } catch { /* Optional navigation restoration. */ }
            } else if (reader.page && !list.notebooks.some(item => item.id === reader.page!.notebook.id)) {
              setListOpen(true);
              try { sessionStorage.removeItem(`codesign-selected:${session.owner_id}`); sessionStorage.removeItem(`codesign-lecture:${session.owner_id}:${reader.page.notebook.id}`); } catch { /* Optional tab draft cleanup. */ }
              window.requestAnimationFrame(() => document.querySelector<HTMLButtonElement>('.nav-new')?.focus());
            }
          }}/>
        <div className="profile">
          <span className="profile-avatar" aria-hidden="true"><Icon name="user"/></span>
          <strong>{preferences?.display_name || session.display_name}</strong>
          <a ref={accountLink} href={session.kind === 'registered' ? '/api/v1/auth/logout' : '/api/v1/auth/login'}>{session.kind === 'registered' ? 'Sign out' : 'Sign in'}</a>
        </div>
      </aside>
      <main id="main" tabIndex={-1} className="reading">
        {new URLSearchParams(window.location.search).has('guest_transfer_error') ? <p role="alert" className="error">We couldn’t confirm whether your guest notebooks were added. Check your notebook list. If they are missing, keep this browser’s cookies and try signing out and back in.</p> : null}
        {reader.error ? <p role="alert" className="error">{reader.error} <button onClick={() => void reader.reload()}>Refresh notebooks</button></p> : null}
        {reader.busy ? <p role="status">Loading saved history…</p> : null}
        {view === 'library' ? <Sources library thread="library" owner={session.owner_id}
          expired={() => void reader.reload()} disabled={workspaceLocked}/> : null}
        {view === 'search' ? <WorkspaceSearch entries={reader.notebooks} summaries={reader.chatSummaries} query={search}
          setQuery={setSearch} input={searchInput} locked={workspaceLocked} openChat={openChat} openNotebook={openFolder}/> : null}
        {view === 'notebook' && folder ? <NotebookPage key={folder.id} notebook={folder} entries={reader.notebooks} summaries={reader.chatSummaries}
          owner={session.owner_id} locked={workspaceLocked} expired={() => void reader.reload()}
          createChat={() => workspaceActions.current?.createChat(folder.id)} openChat={openChat}/> : null}
        {view === 'settings' ? <div className="settings-host" ref={setSettingsHost}/> : null}
        <div className="reading-content" hidden={view !== 'chat'}>
        {parentFolder ? <div className="chat-folder-bar"><button className="chat-folder-back" disabled={workspaceLocked} onClick={() => openFolder(parentFolder.id)}>
          <Icon name="folder"/><span>{parentFolder.name}</span>
        </button></div> : null}
        {reader.page && reader.project ? <Conversation key={`${session.owner_id}:${reader.page.notebook.id}`} page={reader.page} project={reader.project} owner={session.owner_id}
          displayTitle={reader.page.notebook.kind === 'notebook' ? 'Original chat' : undefined}
          onHelp={() => setHelpOpen(true)} preferredIntent={preferences?.default_mode ?? 'lecture'}
          showStarters={preferences?.starter_prompts ?? true} reduceMotion={preferences?.reduce_motion ?? false}
          onboardingRequest={onboardingRequest} busy={reader.busy} externalBlocked={workspaceBlocked} activity={setActivity} refresh={async () => { if (!await reader.open(reader.page!.notebook.id, false, true)) throw new Error('Refresh failed'); }} expired={() => void reader.reload()}
          loadEarlier={() => reader.open(reader.page!.notebook.id, true).then(() => {})}/> : !reader.busy ? <div className="choose-notebook"><span className="welcome-mark"><Icon name="spark"/></span><h2>Make room for a better question.</h2><p>Bring a half-formed thought. We’ll work through it together.</p>
          <div className="empty-workspace-actions"><button className="primary" onClick={startChat} disabled={workspaceLocked}>New Chat</button><button onClick={promptNotebook} aria-haspopup="dialog" disabled={workspaceLocked}><Icon name="plus"/> Create a notebook</button></div>
          <p className="supporting privacy-note">Your work here is not graded.</p></div> : null}
        </div>
      </main>
    </div>
  </>;
}
