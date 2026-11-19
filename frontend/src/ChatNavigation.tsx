/** Keep sidebar organization independent of the selected conversation. */
import { useRef, useState, type DragEvent, type PointerEvent } from 'react';
import { createPortal } from 'react-dom';
import type { ChatSummary, Notebook } from './api';
import { Icon } from './Icon';
import { ChatActions, type ChatCommands } from './ChatActions';
import { originalNotebookChat, recentChats } from './notebookChats';

interface ChatNavigationProps {
  entries: Notebook[];
  currentId?: string;
  folderId?: string;
  summaries: Record<string, ChatSummary>;
  locked: boolean;
  sections: { notebooks: boolean; chats: boolean };
  setSection: (section: 'notebooks' | 'chats', open: boolean) => void;
  newNotebook: () => void;
  open: (id: string) => void;
  openFolder: (id: string) => void;
  move: (id: string, destination: string | null) => Promise<void>;
  commands: ChatCommands;
}

interface HandleDrag {
  pointerId: number;
  x: number;
  y: number;
  moved: boolean;
}

/** Render notebook groups with pointer and desktop drag, plus an accessible move dialog. */
export function ChatNavigation({ entries, currentId, folderId, summaries, locked, sections, setSection, newNotebook, open, openFolder, move, commands }: ChatNavigationProps) {
  const [collapsed, setCollapsed] = useState<string[]>([]);
  const [dragging, setDragging] = useState<Notebook | null>(null);
  const [dropTarget, setDropTarget] = useState<string | null>();
  const [moving, setMoving] = useState(false);
  const [picker, setPicker] = useState<Notebook | null>(null);
  const [actions, setActions] = useState<{ id: string; anchor: HTMLButtonElement } | null>(null);
  const [destination, setDestination] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const dialog = useRef<HTMLDialogElement>(null);
  const pickerReturn = useRef<HTMLButtonElement | null>(null);
  const inFlight = useRef(false);
  const nativeChat = useRef<Notebook | null>(null);
  const handleDrag = useRef<HandleDrag | null>(null);
  const suppressClick = useRef(false);

  const notebooks = entries.filter(entry => entry.kind === 'notebook');
  const groups = new Map<string | null, Notebook[]>();
  for (const entry of entries) {
    if (entry.kind !== 'chat') continue;
    const key = entry.parent_notebook_id ?? null;
    const group = groups.get(key);
    if (group) group.push(entry);
    else groups.set(key, [entry]);
  }
  for (const notebook of notebooks) {
    if (summaries[notebook.id]) groups.set(notebook.id, [...(groups.get(notebook.id) ?? []), originalNotebookChat(notebook)]);
  }
  const looseChats = recentChats(groups.get(null) ?? [], summaries)
    .sort((a, b) => Number(!!b.pinned) - Number(!!a.pinned));
  const disabled = locked || moving;
  const actionChat = entries.find(entry => entry.id === actions?.id);

  function clearDrag() {
    nativeChat.current = null;
    setDragging(null);
    setDropTarget(undefined);
  }

  function startDrag(event: DragEvent<HTMLButtonElement>, chat: Notebook) {
    event.dataTransfer.setData('application/x-codesign-chat', 'move');
    event.dataTransfer.effectAllowed = 'move';
    nativeChat.current = chat;
    setDragging(chat);
  }

  function accepts(chat: Notebook, target: string | null) {
    return !disabled && (chat.parent_notebook_id ?? null) !== target;
  }

  function dropProps(target: string | null) {
    return {
      'data-chat-destination': target ?? '',
      onDragOver(event: DragEvent<HTMLElement>) {
        const chat = nativeChat.current;
        if (!chat || !accepts(chat, target)) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = 'move';
        setDropTarget(target);
      },
      onDragLeave(event: DragEvent<HTMLElement>) {
        if (event.relatedTarget instanceof Node && event.currentTarget.contains(event.relatedTarget)) return;
        setDropTarget(value => value === target ? undefined : value);
      },
      onDrop(event: DragEvent<HTMLElement>) {
        const chat = nativeChat.current;
        if (!chat || !accepts(chat, target)) return;
        event.preventDefault();
        clearDrag();
        void moveTo(chat, target);
      },
    };
  }

  function pointerDestination(event: PointerEvent, chat: Notebook) {
    const hit = document.elementFromPoint(event.clientX, event.clientY)?.closest<HTMLElement>('[data-chat-destination]');
    const target = hit?.dataset.chatDestination;
    return target !== undefined && accepts(chat, target || null) ? target || null : undefined;
  }

  function startHandle(event: PointerEvent<HTMLButtonElement>) {
    if (!event.isPrimary || event.button !== 0) return;
    suppressClick.current = false;
    handleDrag.current = { pointerId: event.pointerId, x: event.clientX, y: event.clientY, moved: false };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function moveHandle(event: PointerEvent<HTMLButtonElement>, chat: Notebook) {
    const gesture = handleDrag.current;
    if (gesture?.pointerId !== event.pointerId || disabled) return;
    if (!gesture.moved) {
      if (Math.hypot(event.clientX - gesture.x, event.clientY - gesture.y) < 8) return;
      gesture.moved = true;
      suppressClick.current = true;
      setDragging(chat);
    }
    setDropTarget(pointerDestination(event, chat));
  }

  function endHandle(event: PointerEvent<HTMLButtonElement>, chat: Notebook) {
    const gesture = handleDrag.current;
    if (gesture?.pointerId !== event.pointerId) return;
    handleDrag.current = null;
    clearDrag();
    if (event.type !== 'pointerup' || !gesture.moved) return;
    const target = pointerDestination(event, chat);
    if (target !== undefined) void moveTo(chat, target);
  }

  async function moveTo(chat: Notebook, target: string | null) {
    if (locked || inFlight.current || (chat.parent_notebook_id ?? null) === target) return;
    inFlight.current = true;
    setMoving(true);
    setError('');
    setNotice('');
    try {
      await move(chat.id, target);
      if (target === null) {
        setSection('chats', true);
      } else {
        setSection('notebooks', true);
        setCollapsed(items => items.filter(id => id !== target));
      }
      setNotice(`Moved “${chat.name}” to ${notebooks.find(entry => entry.id === target)?.name ?? 'Chats'}.`);
      if (dialog.current?.open) {
        pickerReturn.current = null;
        dialog.current.close();
        requestAnimationFrame(() => (document.getElementById(`chat-row-${chat.id}`)
          ?? (target ? document.getElementById(`folder-row-${target}`) : document.getElementById('chat-list-heading')))?.focus());
      }
    } catch {
      setError('Could not confirm the move. Check the destination and try again.');
    } finally {
      inFlight.current = false;
      setMoving(false);
    }
  }

  function showPicker(chat: Notebook, returnFocus: HTMLButtonElement) {
    setPicker(chat);
    pickerReturn.current = returnFocus;
    setDestination(chat.parent_notebook_id ?? '');
    setError('');
    dialog.current?.showModal();
  }

  function chatRow(chat: Notebook) {
    const canManage = chat.kind === 'chat';
    const canDrag = canManage && notebooks.length > 0;
    return <div key={chat.id} className="sidebar-row chat-entry" data-dragging={dragging?.id === chat.id || undefined}>
      {canDrag ? <button className="icon-button sidebar-action chat-drag-handle" aria-label={`Move ${chat.name}`} title="Drag or move chat"
        aria-haspopup="dialog" disabled={disabled} onPointerDown={startHandle} onPointerMove={event => moveHandle(event, chat)}
        onPointerUp={event => endHandle(event, chat)} onPointerCancel={event => endHandle(event, chat)} onLostPointerCapture={event => endHandle(event, chat)}
        onClick={event => { if (event.detail === 0 || !suppressClick.current) showPicker(chat, event.currentTarget); }}><Icon name="grip"/></button> : null}
      <button id={`chat-row-${chat.id}`} className="notebook" title={chat.name} aria-current={currentId === chat.id ? 'page' : undefined}
        aria-label={chat.pinned ? `${chat.name}, pinned` : undefined}
        disabled={disabled} draggable={!disabled && canDrag} onDragStart={event => { if (canDrag) startDrag(event, chat); }}
        onDragEnd={clearDrag} onClick={() => open(chat.id)}>{!canDrag ? <Icon name="chat"/> : null}<span>{chat.name}</span>
        {chat.pinned ? <Icon name="pin"/> : null}</button>
      {canManage ? <button className="icon-button sidebar-action chat-more" aria-label={`Actions for ${chat.name}`} title="Chat actions"
        aria-haspopup="menu" aria-expanded="false" disabled={disabled}
        onClick={event => setActions({ id: chat.id, anchor: event.currentTarget })}><Icon name="more"/></button> : null}
    </div>;
  }

  return <>
    <div className="nav-section-heading">
      <button className="nav-section-title" aria-expanded={sections.notebooks} aria-controls="saved-notebooks"
        onClick={() => setSection('notebooks', !sections.notebooks)}><Icon name={sections.notebooks ? 'chevronDown' : 'chevronRight'}/>Notebooks</button>
      <button className="icon-button notebook-add" aria-label="New notebook" title="New notebook" aria-haspopup="dialog"
        disabled={disabled} onClick={newNotebook}><Icon name="plus"/></button>
    </div>
    <nav id="saved-notebooks" className="workspace-list" hidden={!sections.notebooks} aria-label="Saved notebooks">
      {notebooks.map(notebook => {
        const children = recentChats(groups.get(notebook.id) ?? [], summaries);
        const preview = children.slice(0, 3);
        const expanded = !collapsed.includes(notebook.id);
        const groupId = `notebook-chats-${notebook.id}`;
        return <div key={notebook.id}>
          <div className="sidebar-row" data-drop-target={dropTarget === notebook.id || undefined} {...dropProps(notebook.id)}>
            <button id={`folder-row-${notebook.id}`} className="notebook" title={notebook.name} aria-current={folderId === notebook.id ? 'page' : undefined}
              disabled={disabled} onClick={() => openFolder(notebook.id)}><Icon name="folder"/><span>{notebook.name}</span></button>
            {children.length > 0 ? <button className="icon-button sidebar-action" aria-label={`${expanded ? 'Hide' : 'Show'} chats in ${notebook.name}`}
              aria-expanded={expanded} aria-controls={groupId}
              onClick={() => setCollapsed(items => expanded ? [...items, notebook.id] : items.filter(id => id !== notebook.id))}>
              <Icon name={expanded ? 'chevronDown' : 'chevronRight'}/>
            </button> : null}
          </div>
          {children.length > 0 ? <div id={groupId} className="notebook-children" role="group" aria-label={`Chats in ${notebook.name}`} hidden={!expanded}>
            {preview.map(chatRow)}
            {children.length > preview.length ? <button className="folder-view-all" disabled={disabled}
              onClick={() => openFolder(notebook.id)}>View all chats <span className="sr-only">in {notebook.name}</span></button> : null}
          </div> : null}
        </div>;
      })}
      {notebooks.length === 0 ? <p className="supporting list-empty">No notebooks yet.</p> : null}
    </nav>
    <div className="sidebar-chat-group" data-drop-target={dropTarget === null || undefined} {...dropProps(null)}>
      <button id="chat-list-heading" className="nav-section-title" aria-expanded={sections.chats} aria-controls="saved-chats"
        onClick={() => setSection('chats', !sections.chats)}><Icon name={sections.chats ? 'chevronDown' : 'chevronRight'}/>Chats</button>
      <nav id="saved-chats" className="workspace-list" hidden={!sections.chats} aria-label="Saved chats">
        {looseChats.map(chatRow)}
        {looseChats.length === 0 ? <p className="supporting list-empty">No chats yet.</p> : null}
      </nav>
    </div>
    <div className="sr-only" role="status">{notice}</div>
    {error && !picker ? <p className="nav-move-error supporting" role="alert">{error}</p> : null}
    {actions && actionChat ? <ChatActions key={actions.id} chat={actionChat} anchor={actions.anchor} locked={disabled} canMove={notebooks.length > 0}
      commands={commands} onClose={() => setActions(current => current === actions ? null : current)}
      onMove={() => { setActions(null); showPicker(actionChat, actions.anchor); }}
      report={(message, failed) => { setError(failed ? message : ''); setNotice(failed ? '' : message); }}/> : null}
    {createPortal(<dialog ref={dialog} className="course-dialog notebook-dialog" aria-labelledby="move-chat-heading" aria-describedby="move-chat-name"
      onCancel={event => { if (moving) event.preventDefault(); }} onClose={() => {
        setPicker(null);
        setError('');
        pickerReturn.current?.focus({ preventScroll: true });
        pickerReturn.current = null;
      }}>
      <h2 id="move-chat-heading">Move chat</h2>
      <p className="move-chat-name" id="move-chat-name">{picker?.name}</p>
      {picker ? <form onSubmit={event => { event.preventDefault(); void moveTo(picker, destination || null); }}>
        <label htmlFor="move-chat-destination">Destination</label>
        <select id="move-chat-destination" autoFocus value={destination} disabled={moving} onChange={event => setDestination(event.target.value)}>
          <option value="">Chats</option>
          {notebooks.map(notebook => <option key={notebook.id} value={notebook.id}>{notebook.name}</option>)}
        </select>
        {error ? <p role="alert">{error}</p> : null}
        <div className="notebook-dialog-actions">
          <button type="button" disabled={moving} onClick={() => dialog.current?.close()}>Cancel</button>
          <button className="primary" disabled={disabled || destination === (picker.parent_notebook_id ?? '')} type="submit">{moving ? 'Moving…' : 'Move'}</button>
        </div>
      </form> : null}
    </dialog>, document.body)}
  </>;
}
