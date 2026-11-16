/** CDE2300 lecture and project companion over the shared coaching policy. */
import { useEffect, useRef, useState } from 'react';
import { useReader } from './useReader';
import { Conversation } from './Conversation';

/** Render authentication, notebook navigation, and saved transcript reading states. */
export default function App() {
  const reader = useReader();
  const session = reader.session;
  useEffect(() => {
    if (reader.phase !== 'signed-out' && !(reader.phase === 'error' && reader.error.startsWith('This reader is for student'))) return;
    try {
      for (const key of Object.keys(sessionStorage)) {
        if (key.startsWith('codesign-lecture:') || key.startsWith('codesign-selected:')) sessionStorage.removeItem(key);
      }
    } catch { /* No persistent draft exists when tab storage is blocked. */ }
  }, [reader.phase, reader.error]);
  return <>
    <a className="skip-link" href="#main">Skip to saved work</a>
    <header className="app-header">
      <a className="wordmark" href="/pilot/">CDE2300</a>
      <span className="reader-label">Student companion</span>
      <a className="streamlit-link" href="/">Open Streamlit</a>
    </header>
    {!session ? <main id="main" className="entry">
      <h1>Pick up your questions<br/>and project thinking.</h1>
      <p>Ask about lectures, develop your project, and resume saved work in an existing notebook. Use Streamlit to create notebooks.</p>
      <p className="course-notice">Your chatbot work is never graded and has no association with your course grades. This companion is used for CDE2300. Researchers want to understand how students use it and whether it benefits learning.</p>
      {reader.phase === 'checking' ? <p role="status">Checking your session…</p> : <>
        <div className="entry-actions"><a className="primary action" href="/api/v1/auth/login">Sign in</a>
          <button onClick={() => void reader.startGuest()}>Continue as Guest</button></div>
        <p className="supporting">Sign-in opens Streamlit. Return here after signing in. Guest work stays with this browser; use the same browser to find it again.</p>
      </>}
      {reader.error ? <p role="alert">{reader.error} <button onClick={() => void reader.reload()}>Try again</button></p> : null}
    </main> : <ReaderWorkspace key={session.owner_id} reader={reader}/>}
  </>;
}

/** Keep navigation text ephemeral and reset it with the authenticated owner. */
function ReaderWorkspace({ reader }: { reader: ReturnType<typeof useReader> }) {
  const [search, setSearch] = useState('');
  const [listOpen, setListOpen] = useState(true);
  const toggle = useRef<HTMLButtonElement>(null);
  const searchInput = useRef<HTMLInputElement>(null);
  const session = reader.session!;
  useEffect(() => {
    try {
      // Drafts belong to one verified owner in this tab. Replies are never stored.
      for (const key of Object.keys(sessionStorage)) {
        if (key.startsWith('codesign-lecture:') && !key.startsWith(`codesign-lecture:${session.owner_id}:`)) sessionStorage.removeItem(key);
      }
      const selected = sessionStorage.getItem(`codesign-selected:${session.owner_id}`);
      if (selected && reader.notebooks.some(item => item.id === selected)) {
        setListOpen(false);
        void reader.open(selected);
      }
    } catch { /* Reading still works when browser tab storage is unavailable. */ }
  }, []);
  const visible = reader.notebooks.filter(item => item.name.toLocaleLowerCase().includes(search.toLocaleLowerCase()));
  return <div className="workspace">
      <aside id="notebook-list" className={`notebooks ${listOpen ? 'list-open' : ''}`} aria-label="Your notebooks">
        <div className="notebook-heading"><h1>Notebooks</h1><button className="mobile-only" onClick={() => { setListOpen(false); toggle.current?.focus(); }}>Close list</button></div>
        <label htmlFor="search">Find a notebook</label>
        <input ref={searchInput} id="search" type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder="Search titles"/>
        <nav aria-label="Saved notebooks">
          {visible.map(item => <button key={item.id} className="notebook" aria-current={reader.page?.notebook.id === item.id ? 'page' : undefined}
            disabled={reader.busy} onClick={() => {
              setListOpen(false);
              document.getElementById('main')?.focus();
              try { sessionStorage.setItem(`codesign-selected:${session.owner_id}`, item.id); } catch { /* Optional navigation restoration. */ }
              void reader.open(item.id);
            }}>{item.name}</button>)}
        </nav>
        {visible.length === 0 ? <p className="supporting">{search ? 'No matching notebooks.' : 'No saved notebooks yet. Create one in Streamlit, then refresh this list.'}</p> : null}
        <div className="profile"><strong>{session.display_name}</strong><span>{session.kind === 'guest' ? 'Guest workspace' : 'Student workspace'}</span>
          <button onClick={() => { setSearch(''); void reader.reload(); }}>Refresh notebooks</button>
          <a href="/">Manage session in Streamlit</a></div>
      </aside>
      <main id="main" tabIndex={-1} className="reading">
        <div className="reading-toolbar"><button ref={toggle} className="mobile-only" aria-expanded={listOpen} aria-controls="notebook-list" onClick={() => {
          setListOpen(value => !value);
          if (!listOpen) window.requestAnimationFrame(() => searchInput.current?.focus());
        }}>Notebooks</button></div>
        {reader.error ? <p role="alert" className="error">{reader.error} <button onClick={() => void reader.reload()}>Refresh notebooks</button></p> : null}
        {reader.busy ? <p role="status">Loading saved history…</p> : null}
        {reader.page && reader.project ? <Conversation key={`${session.owner_id}:${reader.page.notebook.id}`} page={reader.page} project={reader.project} owner={session.owner_id}
          busy={reader.busy} refresh={async () => { if (!await reader.open(reader.page!.notebook.id, false, true)) throw new Error('Refresh failed'); }} expired={() => void reader.reload()}
          loadEarlier={() => reader.open(reader.page!.notebook.id, true).then(() => {})}/> : !reader.busy ? <div className="choose-notebook"><h2>Pick up a thread.</h2><p>Choose a notebook to ask a lecture question or revisit saved work.</p></div> : null}
      </main>
    </div>;
}
