import type { ChatSummary, Notebook } from './api';

/** Present an existing notebook conversation under its folder using its original thread ID. */
export function originalNotebookChat(notebook: Notebook): Notebook {
  return { ...notebook, name: 'Original chat', parent_notebook_id: notebook.id };
}

/** Sort by saved message activity with stable results for simultaneous turns. */
export function recentChats(chats: Notebook[], summaries: Record<string, ChatSummary>) {
  return [...chats].sort((a, b) => {
    const left = Date.parse(summaries[a.id]?.activity_at ?? '') || 0;
    const right = Date.parse(summaries[b.id]?.activity_at ?? '') || 0;
    return right - left
      || (summaries[b.id]?.activity_at ?? '').localeCompare(summaries[a.id]?.activity_at ?? '')
      || a.id.localeCompare(b.id);
  });
}
