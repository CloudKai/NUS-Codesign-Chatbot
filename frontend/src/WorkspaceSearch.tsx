import type { Ref } from 'react';
import type { ChatSummary, Notebook } from './api';
import { Icon } from './Icon';
import { originalNotebookChat, recentChats } from './notebookChats';

/** Find saved notebooks and conversations by title in the current workspace. */
export function WorkspaceSearch({ entries, summaries, query, setQuery, input, locked, openChat, openNotebook }: {
  entries: Notebook[]; summaries: Record<string, ChatSummary>; query: string; setQuery: (value: string) => void;
  input: Ref<HTMLInputElement>; locked: boolean; openChat: (id: string) => void; openNotebook: (id: string) => void;
}) {
  const term = query.trim().toLocaleLowerCase();
  const notebooks = new Map(entries.filter(entry => entry.kind === 'notebook').map(entry => [entry.id, entry]));
  const originalChats: Notebook[] = [...notebooks.values()].filter(notebook => summaries[notebook.id])
    .map(notebook => ({ ...originalNotebookChat(notebook), kind: 'chat' }));
  const matches = term ? recentChats([...entries, ...originalChats], summaries)
    .filter(entry => entry.name.toLocaleLowerCase().includes(term)) : [];

  return <section className="workspace-search" aria-labelledby="workspace-search-heading">
    <h1 id="workspace-search-heading">Search</h1>
    <label className="search-field">
      <Icon name="search"/>
      <span className="sr-only">Search notebooks and chats</span>
      <input ref={input} type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Search notebooks and chats…"/>
    </label>
    <p className="search-status supporting" role="status">
      {!term ? 'Find a notebook or chat by title.' : matches.length === 0 ? 'No matching notebooks or chats.' : `${matches.length} ${matches.length === 1 ? 'result' : 'results'}`}
    </p>
    {matches.length ? <ul className="search-results" aria-label="Search results">
      {matches.map(entry => {
        const isNotebook = entry.kind === 'notebook';
        const parent = entry.parent_notebook_id ? notebooks.get(entry.parent_notebook_id) : undefined;
        return <li key={`${entry.kind}:${entry.id}`}>
          <button disabled={locked} onClick={() => (isNotebook ? openNotebook : openChat)(entry.id)}>
            <Icon name={isNotebook ? 'folder' : 'chat'}/>
            <span><strong>{entry.name}</strong><small>{isNotebook ? 'Notebook' : parent?.name ?? 'Chat'}</small></span>
            <Icon name="chevronRight"/>
          </button>
        </li>;
      })}
    </ul> : null}
  </section>;
}
