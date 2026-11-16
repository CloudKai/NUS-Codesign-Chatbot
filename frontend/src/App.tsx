/** Read-only CDE2300 notebook shell; authoring and lecturer work remain in Streamlit. */
import { useRef, useState } from 'react';
import { useReader } from './useReader';

/** Render authentication, notebook navigation, and saved transcript reading states. */
export default function App() {
  const reader = useReader();
  const session = reader.session;
  return <>
    <a className="skip-link" href="#main">Skip to saved work</a>
    <header className="app-header">
      <a className="wordmark" href="/pilot/">CDE2300</a>
      <span className="reader-label">Notebook reader</span>
      <a className="streamlit-link" href="/">Open Streamlit</a>
    </header>
    {!session ? <main id="main" className="entry">
      <h1>Your saved thinking,<br/>ready to revisit.</h1>
      <p>Read your existing notebooks here. Use Streamlit to ask questions, explore evidence, and develop your project.</p>
      <p className="course-notice">Your chatbot work is never graded and has no association with your course grades. This companion is used for CDE2300. Researchers want to understand how students use it and whether it benefits learning.</p>
      {reader.phase === 'checking' ? <p role="status">Checking your session…</p> : <>
        <div className="entry-actions"><a className="primary action" href="/api/v1/auth/login">Sign in</a>
          <button onClick={() => void reader.startGuest()}>Continue as Guest</button></div>
        <p className="supporting">Sign-in opens Streamlit. Return to this reader after signing in. Guest work stays with this browser; use the same browser to find it again.</p>
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
        {reader.page ? <section aria-label="Saved conversation" className="conversation">
          <h2>{reader.page.notebook.name}</h2>
          <p className="supporting">{reader.page.messages.length} of {reader.page.total_count} saved messages. To write or open cited sources, continue in Streamlit.</p>
          {reader.page.next_cursor ? <button disabled={reader.busy} onClick={() => void reader.open(reader.page!.notebook.id, true)}>Load earlier messages</button> : null}
          {reader.page.messages.length === 0 ? <p>No saved messages in this notebook yet.</p> : null}
          {reader.page.messages.map(message => <article className={`message ${message.role === 'user' ? 'student' : 'coach'}`} key={message.id}>
            <h3>{message.role === 'user' ? 'You' : 'Coach'}</h3><div className="message-content">{message.content}</div>
          </article>)}
        </section> : !reader.busy ? <div className="choose-notebook"><h2>Pick up a thread.</h2><p>Choose a notebook to read your saved questions, ideas, and coach feedback.</p></div> : null}
      </main>
    </div>;
}
