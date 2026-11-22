/** Sidebar actions for one chat, including confirmation for permanent deletion. */
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { get, type Notebook, type NotebookSettings } from './api';
import { Icon } from './Icon';

export interface ChatCommands {
  rename: (id: string, name: string) => Promise<void>;
  pin: (id: string, pinned: boolean) => Promise<void>;
  remove: (id: string) => Promise<void>;
  share: (chat: Notebook) => Promise<string>;
}

interface ChatActionsProps {
  chat: Notebook;
  anchor: HTMLButtonElement;
  locked: boolean;
  canMove: boolean;
  commands: ChatCommands;
  onClose: () => void;
  onMove: () => void;
  report: (message: string, failed?: boolean) => void;
}

/** Place a native popover near its row with keyboard navigation and viewport bounds. */
export function ChatActions({ chat, anchor, locked, canMove, commands, onClose, onMove, report }: ChatActionsProps) {
  const [view, setView] = useState<'menu' | 'rename' | 'delete' | 'working'>('menu');
  const [name, setName] = useState(chat.name);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [detail, setDetail] = useState<NotebookSettings['response_detail'] | null>(null);
  const [detailBusy, setDetailBusy] = useState(false);
  const menu = useRef<HTMLDivElement>(null);
  const dialog = useRef<HTMLDialogElement>(null);

  useLayoutEffect(() => {
    if (view === 'menu') {
      const panel = menu.current!;
      panel.showPopover();
      anchor.setAttribute('aria-expanded', 'true');
      const position = () => {
        const row = anchor.getBoundingClientRect();
        const viewport = window.visualViewport;
        const left = (viewport?.offsetLeft ?? 0) + 8;
        const top = (viewport?.offsetTop ?? 0) + 8;
        const right = left + (viewport?.width ?? window.innerWidth) - 16;
        const bottom = top + (viewport?.height ?? window.innerHeight) - 16;
        panel.style.maxWidth = `${Math.max(0, right - left)}px`;
        panel.style.maxHeight = `${Math.max(0, bottom - top)}px`;
        panel.style.left = `${Math.max(left, Math.min(row.right - panel.offsetWidth, right - panel.offsetWidth))}px`;
        panel.style.top = `${Math.max(top, Math.min(row.top - panel.offsetHeight - 4, bottom - panel.offsetHeight))}px`;
      };
      position();
      panel.querySelector<HTMLButtonElement>('button')?.focus({ preventScroll: true });
      const observer = new ResizeObserver(position);
      observer.observe(panel);
      window.visualViewport?.addEventListener('resize', position);
      window.visualViewport?.addEventListener('scroll', position);
      window.addEventListener('resize', position);
      window.addEventListener('scroll', position, true);
      return () => {
        anchor.setAttribute('aria-expanded', 'false');
        observer.disconnect();
        window.visualViewport?.removeEventListener('resize', position);
        window.visualViewport?.removeEventListener('scroll', position);
        window.removeEventListener('resize', position);
        window.removeEventListener('scroll', position, true);
      };
    }
    if (view === 'rename' || view === 'delete') dialog.current?.showModal();
  }, [view, anchor]);

  const settingsPath = `/api/v1/reader/threads/${encodeURIComponent(chat.id)}/settings`;
  useEffect(() => {
    const controller = new AbortController();
    get<NotebookSettings>(settingsPath, controller.signal)
      .then(value => { if (value.notebook.id === chat.id) setDetail(value.response_detail); })
      .catch(() => { /* Without saved settings the response detail choice stays hidden. */ });
    return () => controller.abort();
  }, [settingsPath, chat.id]);

  /** Save the per-chat reply length, then re-read it so the menu shows what the server kept. */
  async function chooseDetail(value: NotebookSettings['response_detail']) {
    if (detailBusy || locked || value === detail) return;
    setDetailBusy(true);
    try {
      await fetch(settingsPath, { method: 'POST', credentials: 'same-origin', cache: 'no-store',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ response_detail: value }) });
    } catch { /* A lost response can still have saved; the read below decides. */ }
    try {
      const saved = await get<NotebookSettings>(settingsPath, new AbortController().signal);
      setDetail(saved.response_detail);
      report(saved.response_detail === value ? `Replies in this chat will be ${value === 'short' ? 'concise' : 'detailed'}.` : 'Could not change response detail. Try again.', saved.response_detail !== value);
    } catch { report('Could not verify response detail. Try again.', true); }
    finally { setDetailBusy(false); close(); }
  }

  function close() {
    onClose();
    requestAnimationFrame(() => {
      if (anchor.isConnected) anchor.focus({ preventScroll: true });
      else document.getElementById('chat-list-heading')?.focus({ preventScroll: true });
    });
  }

  function runImmediate(action: () => Promise<string>) {
    setView('working');
    void action().then(message => report(message), () => report('Could not complete the chat action. Try again.', true)).finally(close);
  }

  async function submit() {
    if (busy || locked) return;
    setBusy(true);
    setError('');
    try {
      if (view === 'rename') await commands.rename(chat.id, name.trim());
      else await commands.remove(chat.id);
      report(view === 'rename' ? 'Chat renamed.' : 'Chat deleted.');
      close();
    } catch {
      setError(view === 'rename' ? 'Could not verify the new name. Try again.' : 'Could not verify the deletion. Check the chat list before trying again.');
    } finally {
      setBusy(false);
    }
  }

  if (view === 'working') return null;
  if (view === 'menu') return createPortal(<div id="chat-actions-menu" ref={menu} className="chat-actions-menu"
    popover="auto" role="menu" aria-label={`Actions for ${chat.name}`} onToggle={event => {
      if (event.currentTarget.isConnected && !event.currentTarget.matches(':popover-open')) onClose();
    }} onKeyDown={event => {
      if (event.key === 'Escape') { event.preventDefault(); close(); return; }
      if (!['ArrowUp', 'ArrowDown', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const items = [...event.currentTarget.querySelectorAll<HTMLButtonElement>('button:not(:disabled)')];
      const index = items.indexOf(document.activeElement as HTMLButtonElement);
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1
        : (index + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
      items[next]?.focus();
    }}>
    <button role="menuitem" disabled={locked} onClick={() => setView('rename')}><Icon name="edit"/> Rename</button>
    <button role="menuitem" disabled={locked} onClick={() => runImmediate(async () => {
      await commands.pin(chat.id, !chat.pinned);
      return chat.pinned ? 'Chat unpinned.' : 'Chat pinned.';
    })}><Icon name="pin"/> {chat.pinned ? 'Unpin' : 'Pin'}</button>
    <button role="menuitem" disabled={locked} onClick={() => runImmediate(() => commands.share(chat))}><Icon name="share"/> Share</button>
    {detail ? <div className="menu-group" role="group" aria-label="Response detail for this chat">
      <span className="menu-group-label" aria-hidden="true">Response detail</span>
      <div className="menu-segmented">
        {([['short', 'Concise'], ['long', 'Detailed']] as const).map(([value, label]) =>
          <button key={value} role="menuitemradio" aria-checked={detail === value} disabled={locked || detailBusy}
            onClick={() => void chooseDetail(value)}>{label}</button>)}
      </div>
    </div> : null}
    <button role="menuitem" className="danger-action" disabled={locked} onClick={() => setView('delete')}><Icon name="trash"/> Delete</button>
    <button role="menuitem" className="move-menu-action" disabled={locked || !canMove} onClick={onMove}><Icon name="folder"/> Move to notebook…</button>
  </div>, document.body);

  const renaming = view === 'rename';
  return createPortal(<dialog ref={dialog} className="course-dialog notebook-dialog" aria-labelledby="chat-action-title"
    onCancel={event => { event.preventDefault(); if (!busy) close(); }}>
    <h2 id="chat-action-title">{renaming ? 'Rename chat' : 'Delete chat?'}</h2>
    <form onSubmit={event => { event.preventDefault(); void submit(); }}>
      {renaming ? <>
        <label htmlFor="chat-action-name">Chat name</label>
        <input id="chat-action-name" autoFocus required maxLength={120} value={name} onChange={event => setName(event.target.value)}/>
      </> : <p>Delete “{chat.name}” and its conversation, sources, and feedback?</p>}
      {error ? <p role="alert">{error}</p> : null}
      <div className="notebook-dialog-actions">
        <button type="button" autoFocus={!renaming} disabled={busy} onClick={close}>Cancel</button>
        <button className={renaming ? 'primary' : 'danger-action'} type="submit"
          disabled={locked || busy || (renaming && (!name.trim() || name.trim() === chat.name))}>{renaming ? 'Save name' : 'Delete chat'}</button>
      </div>
    </form>
  </dialog>, document.body);
}
