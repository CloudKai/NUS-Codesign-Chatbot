/** Folder landing page for chats and the notebook's reusable evidence. */
import { useRef, useState } from 'react';
import type { ChatSummary, Notebook } from './api';
import { Icon } from './Icon';
import { relativeTime } from './HomeView';
import { originalNotebookChat, recentChats } from './notebookChats';
import { Sources } from './Sources';

interface NotebookPageProps {
  notebook: Notebook;
  entries: Notebook[];
  summaries: Record<string, ChatSummary>;
  owner: string;
  locked: boolean;
  expired: () => void;
  createChat: () => void;
  openChat: (id: string) => void;
}

const views = ['Chats', 'Sources'] as const;

/** Render the full notebook conversation list and the existing notebook source manager. */
export function NotebookPage({ notebook, entries, summaries, owner, locked, expired, createChat, openChat }: NotebookPageProps) {
  const [tab, setTab] = useState<(typeof views)[number]>('Chats');
  const tabs = useRef<Array<HTMLButtonElement | null>>([]);
  const children = entries.filter(entry => entry.parent_notebook_id === notebook.id);
  if (summaries[notebook.id]) children.push(originalNotebookChat(notebook));
  const chats = recentChats(children, summaries).sort((a, b) => Number(b.pinned) - Number(a.pinned));

  return <section className="notebook-page" aria-labelledby="folder-title">
    <header className="folder-heading">
      <h1 id="folder-title"><Icon name="folder"/><span>{notebook.name}</span></h1>
      <button className="primary folder-new-chat" disabled={locked} onClick={createChat}>
        <Icon name="plus"/> New chat in this notebook
      </button>
    </header>
    <div className="folder-tabs" role="tablist" aria-label="Notebook views">
      {views.map((view, index) => <button key={view} type="button" ref={element => { tabs.current[index] = element; }}
        id={`folder-tab-${view}`} role="tab" aria-selected={tab === view} aria-controls={`folder-panel-${view}`}
        tabIndex={tab === view ? 0 : -1} onClick={() => setTab(view)} onKeyDown={event => {
          if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
          event.preventDefault();
          const next = event.key === 'Home' ? 0 : event.key === 'End' ? views.length - 1 : (index + 1) % views.length;
          setTab(views[next]);
          tabs.current[next]?.focus();
        }}>{view}</button>)}
    </div>
    <section id="folder-panel-Chats" role="tabpanel" aria-labelledby="folder-tab-Chats" tabIndex={0} hidden={tab !== 'Chats'}>
      {chats.length ? <ul className="folder-chats">{chats.map(chat => {
        const summary = summaries[chat.id];
        const date = new Date(summary?.activity_at ?? '');
        const when = relativeTime(summary?.activity_at);
        return <li key={chat.id}><button className="folder-chat" disabled={locked} onClick={() => openChat(chat.id)}>
          <span className="folder-chat-text">
            <strong>{chat.name}{chat.pinned ? <Icon name="pin"/> : null}</strong>
            {summary?.preview ? <span className="folder-chat-preview">{summary.preview}</span> : null}
          </span>
          {when ? <time dateTime={date.toISOString()} title={date.toLocaleString()}>{when}</time> : null}
        </button></li>;
      })}</ul> : <p className="folder-empty supporting">Start a chat here to use this notebook’s shared sources.</p>}
    </section>
    <section id="folder-panel-Sources" role="tabpanel" aria-labelledby="folder-tab-Sources" tabIndex={0} hidden={tab !== 'Sources'}>
      {tab === 'Sources' ? <Sources embedded thread={notebook.id} owner={owner} disabled={locked} expired={expired}/> : null}
    </section>
  </section>;
}
