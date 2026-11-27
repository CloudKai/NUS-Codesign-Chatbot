/** CDE2300 lecture and project companion over the shared coaching policy. */
import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import { SIGN_OUT_SIGNAL, useReader } from './useReader';
import { Conversation } from './Conversation';
import { createArtifact } from './api/client';
import { ChatNavigation } from './ChatNavigation';
import { Sources } from './Sources';
import { NotebookPage } from './NotebookPage';
import { WorkspaceSearch } from './WorkspaceSearch';
import type { Preferences } from './api';
import { WorkspaceTools, type WorkspaceActions } from './WorkspaceTools';
import { Icon } from './Icon';
import { HomeView } from './HomeView';
import { ResizeHandle, SIDEBAR_LIMITS, WorkspaceLayoutContext, useWorkspaceLayout, applyLayoutStyle } from './workspaceLayout';
import { openWorkspaceRoute, useWorkspaceRoute, type WorkspaceRoute } from './workspaceRoute';
import type { CanvasSelection, ArtifactSelection } from './chatLifecycle';

// Tiptap and React Flow are only needed on their routed editor views, so they
// load behind dynamic imports: the chat-first startup bundle stays free of them
// while deep links still mount the same components (measured in
// tests/browser/route_load.spec.ts).
const ArtifactEditor = lazy(() => import('./ArtifactEditor').then(m => ({ default: m.ArtifactEditor })));
const CanvasEditor = lazy(() => import('./CanvasEditor').then(m => ({ default: m.CanvasEditor })));

/** Indeterminate status while a lazily imported editor chunk loads; deep links stay hosted. */
function EditorFallback() {
  return <p className="editor-loading" role="status">Loading editor…</p>;
}

/** Render authentication, notebook navigation, and saved transcript reading states. */
export default function App() {
  const reader = useReader();
  const session = reader.session;
  useEffect(() => {
    if (reader.phase !== 'signed-out' && !(reader.phase === 'error' && reader.error === 'This account cannot access the student workspace.')) return;
    try {
      for (const key of Object.keys(sessionStorage)) {
        if (['codesign-mode:', 'codesign-lecture:', 'codesign-selected:', 'codesign-checkin:', 'codesign-starters:', 'codesign-review:'].some(prefix => key.startsWith(prefix))) sessionStorage.removeItem(key);
      }
    } catch { /* No persistent draft exists when tab storage is blocked. */ }
  }, [reader.phase, reader.error]);
  return <>
    <a className="skip-link" href="#main">Skip to saved work</a>
    {!session ? <><header className="app-header"><Brand/></header><main id="main" className="entry">
      <h1>Pick up your questions<br/>and project thinking.</h1>
      <p>Improve an existing design, develop a project, and resume saved work in your notebooks.</p>
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
  // The typed URL is the navigation truth; back/forward, refresh and deep links all resolve here.
  const route = useWorkspaceRoute();
  const view = route.view;
  const folderId = route.view === 'notebook' ? route.folderId : undefined;
  const [settingsReturn, setSettingsReturn] = useState<WorkspaceRoute>({ view: 'home' });
  const [settingsHost, setSettingsHost] = useState<HTMLDivElement | null>(null);
  const [preferences, setPreferences] = useState<Preferences | null>(reader.preferences);
  const [intentRequest, setIntentRequest] = useState<{ id: string; intent: 'project' | 'improve'; n: number }>();
  const [search, setSearch] = useState('');
  const [activity, setActivity] = useState(false);
  const [workspaceBlocked, setWorkspaceBlocked] = useState(false);
  const layout = useWorkspaceLayout();
  // The saved panel width rides a CSSOM rule: the production CSP blocks inline style attributes.
  useEffect(() => { applyLayoutStyle('workspace', { '--nav-w': `${layout.navWidth}px` }); }, [layout.navWidth]);
  // The sidebar is docked when it fits beside the chat. Otherwise it is an icon rail, with the full list as a drawer on demand.
  const navDocked = layout.nav === 'docked';
  const [drawerOpen, setDrawerOpen] = useState(false);
  const listOpen = navDocked || drawerOpen;
  const overlay = drawerOpen && !navDocked;
  const workspaceActions = useRef<WorkspaceActions>(null);
  const pendingIntent = useRef<'project' | 'improve'>(undefined);
  const startIntents = useRef<Record<string, 'project' | 'improve'>>({});
  const [sections, setSections] = useState({ notebooks: true, chats: true });
  const [canvasSelection, setCanvasSelection] = useState<CanvasSelection | null>(null);
  const [artifactSelection, setArtifactSelection] = useState<ArtifactSelection | null>(null);
  const setSection = (section: keyof typeof sections, open: boolean) => setSections(value => ({ ...value, [section]: open }));
  const promptNotebook = () => workspaceActions.current?.promptNotebook();
  const workspaceLocked = activity || reader.busy || workspaceBlocked;
  const closeMobileList = () => { if (!navDocked) setDrawerOpen(false); };
  useEffect(() => { if (navDocked) setDrawerOpen(false); }, [navDocked]);
  /** Dock the sidebar when it fits, otherwise slide the full list over the page. */
  function showNavigation() {
    if (navDocked) return;
    if (layout.canDockNav) layout.setNavPreference('expanded');
    else setDrawerOpen(true);
  }
  const toggle = useRef<HTMLButtonElement>(null);
  const railToggle = useRef<HTMLButtonElement>(null);
  const accountLink = useRef<HTMLAnchorElement>(null);
  const helpDialog = useRef<HTMLDialogElement>(null);
  function openSearch() {
    openWorkspaceRoute({ view: 'search' });
    closeMobileList();
    searchInput.current?.focus();
  }
  function openNavigation() {
    showNavigation();
    window.requestAnimationFrame(() => document.getElementById('collapse-navigation')?.focus());
  }
  function closeNavigation() {
    if (navDocked) layout.setNavPreference('collapsed');
    else setDrawerOpen(false);
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
  const readerRef = useRef(reader);
  readerRef.current = reader;
  const attemptedLink = useRef<string | null>(null);
  useEffect(() => {
    try {
      // Drafts belong to one verified owner in this tab. Replies are never stored.
      for (const key of Object.keys(sessionStorage)) {
        for (const prefix of ['codesign-mode:', 'codesign-lecture:', 'codesign-checkin:', 'codesign-starters:']) {
          if (key.startsWith(prefix) && !key.startsWith(`${prefix}${session.owner_id}:`)) sessionStorage.removeItem(key);
        }
      }
    } catch { /* Reading still works when browser tab storage is unavailable. */ }
  }, []);
  // The typed URL drives the open flow: deep links, refresh and back/forward all resolve here,
  // and a foreign, deleted or expired link shows no private data and returns to the default view.
  useEffect(() => {
    if (route.view !== 'chat' || reader.phase !== 'ready') return;
    if (reader.page?.notebook.id === route.threadId) { attemptedLink.current = null; return; }
    if (reader.busy || attemptedLink.current === route.threadId) return;
    attemptedLink.current = route.threadId;
    void reader.open(route.threadId).then(result => {
      const latest = readerRef.current;
      if (result !== true && attemptedLink.current === route.threadId
        && latest.page?.notebook.id !== route.threadId && !latest.busy) {
        attemptedLink.current = null;
        openWorkspaceRoute({ view: 'home' }, { replace: true });
      } else if (result === true) attemptedLink.current = null;
    });
  }, [route, reader.phase, reader.busy, reader.page]);
  function startChat(intent?: 'project' | 'improve') {
    if (workspaceLocked) return;
    pendingIntent.current = intent;
    if (reader.page?.notebook.kind === 'chat' && !reader.page.notebook.parent_notebook_id && reader.page.total_count === 0) {
      pendingIntent.current = undefined;
      // The empty chat is already mounted, so tell it which mode the student asked to start in.
      const emptyId = reader.page.notebook.id;
      if (intent) setIntentRequest(value => ({ id: emptyId, intent, n: (value?.n ?? 0) + 1 }));
      openWorkspaceRoute({ view: 'chat', threadId: emptyId });
      closeMobileList();
      window.requestAnimationFrame(() => document.getElementById('lecture-question')?.focus({ preventScroll: true }));
    } else {
      workspaceActions.current?.createChat();
    }
  }
  function openHome() {
    openWorkspaceRoute({ view: 'home' });
    setSearch('');
    closeMobileList();
    window.requestAnimationFrame(() => document.getElementById('main')?.focus({ preventScroll: true }));
  }
  function openChat(id: string) {
    openWorkspaceRoute({ view: 'chat', threadId: id });
    setSearch('');
    closeMobileList();
    document.getElementById('main')?.focus();
  }
  function openFolder(id: string) {
    openWorkspaceRoute({ view: 'notebook', folderId: id });
    setSearch('');
    closeMobileList();
    window.requestAnimationFrame(() => document.getElementById('main')?.focus({ preventScroll: true }));
  }
  function openLibrary() {
    openWorkspaceRoute({ view: 'library' });
    closeMobileList();
  }
  const folder = reader.notebooks.find(item => item.id === folderId && item.kind === 'notebook');
  const selectedChat = reader.page?.notebook;
  const parentId = selectedChat?.kind === 'notebook' ? selectedChat.id : selectedChat?.parent_notebook_id;
  const parentFolder = reader.notebooks.find(item => item.id === parentId && item.kind === 'notebook');
  const showHome = view === 'home' || (view === 'chat' && !reader.page && !reader.busy);
  const folderSettings = view === 'notebook' || (view === 'settings' && settingsReturn.view === 'notebook');

  return <WorkspaceLayoutContext.Provider value={layout}>
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
      <p>Get feedback on an existing design, or work through your project in Design coaching.</p>
      <p>Use the Thinking Path to review your progress. When the coach recommends a new stage, you decide whether to move on.</p>
      <form method="dialog"><button>Done</button></form>
    </dialog>
    <div className={`workspace ${listOpen ? 'nav-open' : 'nav-collapsed'}`} data-nav={layout.nav}>
      {overlay ? <button className="drawer-backdrop" aria-label="Close navigation" onClick={closeNavigation}/> : null}
      {!listOpen ? <nav className="navigation-rail" aria-label="Workspace shortcuts">
        <button ref={railToggle} className="icon-button" aria-label="Expand navigation" title="Expand navigation" onClick={openNavigation}><Icon name="panel"/></button>
        <button className="icon-button" aria-label="Home" title="Home" aria-current={showHome ? 'page' : undefined} onClick={openHome}><Icon name="home"/></button>
        <button className="icon-button" aria-label="New Chat" title="New Chat" disabled={workspaceLocked} onClick={() => startChat()}><Icon name="edit"/></button>
        <button className="icon-button" aria-label="Search" aria-current={view === 'search' ? 'page' : undefined} aria-keyshortcuts="Meta+K Control+K" title="Search notebooks and chats" onClick={openSearch}><Icon name="search"/></button>
        <button className="icon-button" aria-label="Library" title="Library" onClick={openLibrary}><Icon name="book"/></button>
        <button className="icon-button rail-account" aria-label="Account" title="Account" aria-controls="notebook-list" onClick={() => {
          showNavigation();
          window.requestAnimationFrame(() => accountLink.current?.focus());
        }}><span className="profile-avatar"><Icon name="user"/></span></button>
      </nav> : null}
      <aside onKeyDown={event => { if (overlay && event.key === 'Escape' && !event.defaultPrevented && event.currentTarget.contains(event.target as Node)) closeNavigation(); }} id="notebook-list" className={`notebooks ${listOpen ? 'list-open' : ''} ${overlay ? 'overlay' : ''}`} aria-label="Your notebooks">
        <div className="notebook-heading"><span>Co-design</span>
          <button id="collapse-navigation" className="icon-button" aria-label="Collapse navigation" title="Collapse navigation" onClick={closeNavigation}><Icon name="panel"/></button></div>
        <button className="nav-home" aria-current={showHome ? 'page' : undefined} onClick={openHome}><Icon name="home"/> Home</button>
        <button className="nav-new" disabled={workspaceLocked} onClick={() => startChat()}><Icon name="edit"/> New Chat</button>
        <button className="nav-search-link" aria-current={view === 'search' ? 'page' : undefined} aria-keyshortcuts="Meta+K Control+K" onClick={openSearch}><Icon name="search"/> Search<kbd aria-hidden="true">{/Mac|iPhone|iPad/.test(navigator.platform) ? '⌘K' : 'Ctrl K'}</kbd></button>
        <button className="nav-library" aria-current={view === 'library' ? 'page' : undefined} onClick={openLibrary}><Icon name="book"/> Library</button>
        <ChatNavigation entries={reader.notebooks} currentId={view === 'chat' ? reader.page?.notebook.id : undefined}
          folderId={view === 'notebook' ? folderId : undefined} summaries={reader.chatSummaries}
          locked={workspaceLocked} sections={sections} setSection={setSection} newNotebook={promptNotebook}
          open={openChat} openFolder={openFolder} move={reader.moveChat}
          commands={{ rename: reader.renameChat, pin: reader.pinChat, remove: reader.deleteChat, share: reader.shareChat }}/>
        <WorkspaceTools ref={workspaceActions} themeHost={themeHost} settingsHost={settingsHost}
          session={session} initialPreferences={reader.preferences} onPreferences={setPreferences}
          openSettings={() => { if (view !== 'settings') setSettingsReturn(route); openWorkspaceRoute({ view: 'settings' }); closeMobileList(); }}
          closeSettings={() => {
            // The explicit back button mirrors browser Back; a vanished folder returns to the default view.
            openWorkspaceRoute(settingsReturn.view === 'notebook' && !folder ? { view: 'home' } : settingsReturn);
            document.getElementById('main')?.focus();
          }}
          thread={folderSettings ? folder?.id : selectedChat?.id} disabled={activity || reader.busy}
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
              if (pendingIntent.current) startIntents.current[created] = pendingIntent.current;
              pendingIntent.current = undefined;
              if (!await reader.open(created)) throw new Error('Created workspace could not open');
              openWorkspaceRoute({ view: 'chat', threadId: created }); setSearch(''); closeMobileList();
              setSection(entry.parent_notebook_id ? 'notebooks' : 'chats', true);
              window.requestAnimationFrame(() => document.getElementById('lecture-question')?.focus({ preventScroll: true }));
            } else if (folderSettings && folderId && !list.notebooks.some(item => item.id === folderId)) {
              setSettingsReturn({ view: 'home' });
              openWorkspaceRoute({ view: 'home' }, { replace: true });
            } else if (reader.page?.notebook.id
              && !list.notebooks.some(item => item.id === reader.page?.notebook.id)) {
              showNavigation();
              try {
                sessionStorage.removeItem(`codesign-selected:${session.owner_id}`);
                sessionStorage.removeItem(`codesign-mode:${session.owner_id}:${reader.page.notebook.id}`);
                sessionStorage.removeItem(`codesign-lecture:${session.owner_id}:${reader.page.notebook.id}`);
              } catch { /* Optional tab draft cleanup. */ }
              window.requestAnimationFrame(() => document.querySelector<HTMLButtonElement>('.nav-new')?.focus());
            }
          }}/>
        <div className="profile">
          <span className="profile-avatar" aria-hidden="true"><Icon name="user"/></span>
          <strong>{preferences?.display_name || session.display_name}</strong>
          <a ref={accountLink} href={session.kind === 'registered' ? '/api/v1/auth/logout' : '/api/v1/auth/login'}
            onClick={() => {
              if (session.kind !== 'registered') return;
              try { localStorage.setItem(SIGN_OUT_SIGNAL, String(Date.now())); }
              catch { /* Same-tab logout still uses the server flow. */ }
            }}>{session.kind === 'registered' ? 'Sign out' : 'Sign in'}</a>
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
          createChat={() => workspaceActions.current?.createChat(folder.id)} openChat={openChat}
          openArtifact={artifactId => openWorkspaceRoute({ view: 'artifact', folderId: folder.id, artifactId })}
          createArtifact={async (title, kind) => {
            const created = await createArtifact(folder.id, title, { type: 'doc', content: [] },
              new AbortController().signal, kind);
            return created;
          }}
          openCanvas={canvasId => openWorkspaceRoute({ view: 'canvas', folderId: folder.id, canvasId })}/> : null}
        {view === 'artifact' && route.view === 'artifact' ? <Suspense fallback={<EditorFallback/>}><ArtifactEditor owner={session.owner_id} threadId={route.folderId}
          artifactId={route.artifactId} expired={() => void reader.reload()} onClose={() => openFolder(route.folderId)}
          onDiscuss={(artifactId, revision, paragraph, label) => {
            setArtifactSelection({ artifactId, revision, paragraph, label });
            // The family's original notebook chat carries the saved discussion.
            openChat(route.folderId);
          }}/></Suspense> : null}
        {view === 'canvas' && route.view === 'canvas' ? <Suspense fallback={<EditorFallback/>}><CanvasEditor owner={session.owner_id} threadId={route.folderId}
          canvasId={route.canvasId} expired={() => void reader.reload()} onClose={() => openFolder(route.folderId)}
          onDiscuss={(canvasId, revision, nodeIds, label, purpose) => {
            setCanvasSelection({ canvasId, revision, nodeIds, label, purpose });
            // The family's original notebook chat carries the saved discussion.
            openChat(route.folderId);
          }}/></Suspense> : null}
        {showHome ? <HomeView owner={session.owner_id} name={preferences?.display_name || (session.kind === 'guest' ? '' : session.display_name)}
          entries={reader.notebooks} summaries={reader.chatSummaries} locked={workspaceLocked} openChat={openChat} startChat={startChat}
          expired={() => void reader.reload()}
          openArtifact={(folderId, artifactId) => openWorkspaceRoute({ view: 'artifact', folderId, artifactId })}
          openCanvas={(folderId, canvasId) => openWorkspaceRoute({ view: 'canvas', folderId, canvasId })}/> : null}
        {view === 'settings' ? <div className="settings-host" ref={setSettingsHost}/> : null}
        <div className="reading-content" hidden={view !== 'chat' || showHome}>
        {reader.page && reader.project ? <Conversation key={`${session.owner_id}:${reader.page.notebook.id}`} page={reader.page} project={reader.project} owner={session.owner_id}
          canvasSelection={canvasSelection} onCanvasSelectionConsumed={() => setCanvasSelection(null)}
          artifactSelection={artifactSelection} onArtifactSelectionConsumed={() => setArtifactSelection(null)}
          seededBookmarks={reader.bookmarks}
          displayTitle={reader.page.notebook.kind === 'notebook' ? 'Original chat' : undefined}
          parent={parentFolder ? { name: parentFolder.name, open: () => openFolder(parentFolder.id), disabled: workspaceLocked } : undefined}
          onHelp={() => setHelpOpen(true)} preferredIntent={preferences?.default_mode ?? 'improve'}
          showStarters={preferences?.starter_prompts ?? true}
          summary={reader.chatSummaries[reader.page.notebook.id]} startIntent={startIntents.current[reader.page.notebook.id]}
          intentRequest={intentRequest} busy={reader.busy} externalBlocked={workspaceBlocked} activity={setActivity}
          refresh={async () => {
            const id = reader.page?.notebook.id;
            if (!id || !await reader.open(id, false, true)) throw new Error('Refresh failed');
          }} expired={() => void reader.reload()}
          locateMessage={id => (reader.page ? reader.open(reader.page.notebook.id, false, true, id).then(result => !!result) : Promise.resolve(false))}
          loadEarlier={() => { const id = reader.page?.notebook.id; return id ? reader.open(id, true).then(() => {}) : Promise.resolve(); }}/> : null}
        </div>
      </main>
      {navDocked ? <ResizeHandle side="sidebar" label="Resize sidebar" value={layout.navWidth} min={SIDEBAR_LIMITS.min} max={layout.sidebarMax}
        onResize={layout.resizeSidebar} onReset={layout.resetSidebar}/> : null}
    </div>
  </WorkspaceLayoutContext.Provider>;
}
